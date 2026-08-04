"""共用匯入管線：dry-run 隔離與逐列執行骨架。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import DomainError
from app.ingestion.parsing import CellError
from app.ingestion.schema import EntitySpec
from app.schemas.common import ErrorGroup, ImportResult, RowResult

# 成功列只回樣本：確認欄位有對上不需要看一萬列。
_SAMPLE_LIMIT = 20
# 每組錯誤附幾個列號，讓使用者找得到但不洗版。
_GROUP_ROWS = 10
# errors 是保留給舊呼叫端相容的扁平清單（見 ImportResult docstring）；
# error_groups 才是使用者真正該看的東西，這裡只夠給一個大致印象，不能讓一份
# 全壞的大檔案把 payload 撐到幾 MB——尤其 dry-run 在選檔當下就自動打一次。
_ERROR_MSG_LIMIT = 50

# pydantic 驗證失敗的欄位層級原因 → 中文樣板。ge/le/gt/lt 的界限值從 ctx 動態取。
_BOUND_OPS = {
    "greater_than": "大於",
    "greater_than_equal": "大於等於",
    "less_than": "小於",
    "less_than_equal": "小於等於",
}

# 只有這些跨欄位 model_validator 會在匯入路徑上被踩到（見
# app/schemas/{contract,generation,consumption}.py）；逐字對照成中文，而不是
# 讓使用者看見 Python 例外原文。
_VALUE_ERROR_ZH = {
    "period_end must not be before period_start": "區間迄不能早於區間起",
    "end_date must not be before start_date": "結束日不能早於起始日",
    "monthly_shares must have exactly 12 values": "月別配比必須剛好 12 個數字",
    "monthly_shares must be non-negative": "月別配比不可為負數",
    "monthly_shares must sum to a positive value": "月別配比加總必須大於 0",
    (
        "at least one of contracted_energy_mwh or "
        "contracted_percentage must be provided"
    ): "年度合約量與案場發電比例至少要填一個",
}


@contextmanager
def dry_run_session(db: Session) -> Iterator[Session]:
    """在外層 session 自己的連線上開一個 SAVEPOINT，離開時退回。

    綁在同一條連線是刻意的：測試用 ``sqlite://`` ＋ ``StaticPool``，整個
    engine 共用一條 DBAPI 連線，另開連線會撞上「cannot start a transaction
    within a transaction」。``join_transaction_mode="create_savepoint"`` 讓
    ``BaseRepository.create()`` 內部的 ``commit()`` 只是釋放 SAVEPOINT，
    外層不受影響——所以 dry-run 走的是與真匯入完全相同的寫入路徑。

    前置條件（未寫進型別，呼叫端必須自己遵守）：外層 ``db`` 進來時不能帶著
    已 flush 但未 commit 的異動。SAVEPOINT rollback 只會退回這個 context
    manager 自己開的那段，外層若已經 flush 過東西，session 仍會以為那些異動
    留著，實際上已經跟著退回去了。今天每個呼叫端傳進來的都是全新的 request
    session，這個前提不會被打破；assert 只抓得到「還沒 flush 的新物件／
    已 flush 但仍 dirty 的物件」這兩種情況，抓不到「已 flush 且乾淨」的
    異動，所以是盡力而為，不是完整證明。
    """
    assert not db.new and not db.dirty, (
        "dry_run_session 的前置條件是外層 session 沒有待處理的異動；"
        "呼叫端必須傳入一個乾淨的 session"
    )
    conn = db.connection()
    savepoint = conn.begin_nested()
    factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    scoped = factory()
    try:
        yield scoped
    finally:
        scoped.close()
        if savepoint.is_active:
            savepoint.rollback()
        db.expire_all()


class Handler(Protocol):
    def preload(self, db: Any) -> dict[str, Any]: ...
    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]: ...
    def locate(
        self, db: Any, row: dict[str, str], ctx: dict[str, Any]
    ) -> Any | None: ...
    def create(self, db: Any, payload: dict[str, Any]) -> None: ...
    def update(self, db: Any, existing: Any, payload: dict[str, Any]) -> list[str]: ...


def _key_of(spec: EntitySpec, row: dict[str, str]) -> str:
    return "/".join((row.get(c) or "").strip() for c in spec.natural_key)


def _group(errors: list[tuple[int, str | None, str, str | None]]) -> list[ErrorGroup]:
    """依 (欄位, 原因) 收斂。payload 大小由錯誤的種類數決定，不由列數決定。

    ``reason`` 本身必須不帶原值（見 parsing._reason 的說明）才收斂得起來——
    兩千列同一欄格式錯但值都不同，reason 一樣就是一組，值分別進各自的
    ``sample_value``。
    """
    buckets: OrderedDict[tuple[str | None, str], ErrorGroup] = OrderedDict()
    for row_no, field, reason, value in errors:
        key = (field, reason)
        group = buckets.get(key)
        if group is None:
            buckets[key] = ErrorGroup(
                field=field,
                message=reason,
                count=1,
                sample_rows=[row_no],
                sample_value=value,
            )
        else:
            group.count += 1
            if len(group.sample_rows) < _GROUP_ROWS:
                group.sample_rows.append(row_no)
    return list(buckets.values())


def _check_header(
    spec: EntitySpec,
    rows: list[dict[str, str]],
    fieldnames: tuple[str, ...] | None,
) -> ErrorGroup | None:
    """缺自然鍵是整檔的問題：連是哪一列都定不下來，逐列報也沒有意義。

    只檢查自然鍵（不是所有必填欄）——這是刻意放寬，讓「只更新既有資料某幾欄」
    的部分更新檔（如只給 contract_number,price_per_kwh）能通過標題檢查。
    §4.7 承諾「只更新 CSV 有給且非空的欄位」，若標題檢查仍要求全部必填欄都在，
    這種檔案永遠會被整檔擋下，兩條規則互相矛盾。真正建立新列時漏填的必填欄，
    由每一列的 ``_require_for_create``（見 csv_importer.py）攔下，給出一則
    per-row 的中文錯誤，不需要在標題這關就擋。

    標題檢查不能只看 ``rows[0]``：一個標題全錯、但也因此一列資料都解析不出來
    的檔案，``rows`` 會是空的，若因此放行就等於告訴使用者「匯入成功、0 筆」，
    比報錯更誤導。``fieldnames``（來自 ``csv_importer.parse_csv``）在資料列
    是 0 筆時仍然帶著實際讀到的標題，讓這個檢查照樣能跑。
    """
    if rows:
        present = set(rows[0])
    elif fieldnames:
        present = set(fieldnames)
    else:
        return None
    missing = [c for c in spec.natural_key if c not in present]
    if not missing:
        return None
    labels = "、".join(
        f"{spec.column(m).label}（{m}）" for m in missing  # type: ignore[union-attr]
    )
    return ErrorGroup(
        field=None,
        message=f"標題列缺少必填欄位：{labels}。請用「下載範本」取得正確的標題列。",
        count=1,
        sample_rows=[1],
    )


def _validation_errors(
    spec: EntitySpec, exc: PydanticValidationError
) -> list[tuple[str | None, str, str | None]]:
    """把 pydantic 的英文驗證錯誤轉成 (欄位, 中文原因, 原值) 的清單。

    一個 ValidationError 可能包含好幾個欄位的錯誤，逐一轉換，這樣同一種錯誤
    才能跟其他列的同一種錯誤一起被 ``_group`` 收斂。
    """
    out: list[tuple[str | None, str, str | None]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        field = str(loc[0]) if loc else None
        column = spec.column(field) if field else None
        # column 找不到時（loc 指到 spec 沒宣告的內部欄位，如外鍵解析後的
        # wind_farm_id／customer_id）不要把原始英文欄名塞進中文句子——退回
        # 這個實體的中文名，至少讀起來是通順的一句話。
        label = column.label if column is not None else spec.label
        kind = err.get("type", "")
        # loc 為空時 err["input"] 是整個 payload，不是單一值，不能放進
        # sample_value（那會把整包資料印出來）。
        value = str(err["input"]) if field is not None and "input" in err else None
        if kind == "missing":
            reason = f"{label}為必填，不可空白"
        elif kind in _BOUND_OPS:
            ctx = err.get("ctx") or {}
            bound = next(iter(ctx.values()), "")
            reason = f"{label}必須{_BOUND_OPS[kind]} {bound}"
        elif kind == "enum":
            # enum 不合法：把允許值附進訊息，讓使用者不必回頭查 schema 端點
            # 就知道該改成什麼——這正是本次要修的「照著面板打卻被拒絕」。
            ctx = err.get("ctx") or {}
            expected = ctx.get("expected")
            reason = (
                f"{label}不合法，允許值為 {expected}" if expected else f"{label}不合法"
            )
        elif kind == "value_error":
            ctx = err.get("ctx") or {}
            raw_msg = str(ctx["error"]) if "error" in ctx else err.get("msg", "")
            if raw_msg in _VALUE_ERROR_ZH:
                reason = _VALUE_ERROR_ZH[raw_msg]
            else:
                # 未知的跨欄位規則：原始英文訊息可能夾帶值（如 IntegrityError
                # 引用失敗的參數），不能直接放進 reason——否則每一列的訊息都
                # 不一樣，_group 收斂不起來。改放進 value，跟 _resolve_code／
                # 通用例外分支收斂的做法一致。
                reason = f"{label}不合法"
                value = raw_msg
        else:
            reason = f"{label}不合法"
        out.append((field, reason, value))
    return out


def run_import(
    db: Any,
    spec: EntitySpec,
    rows: Iterable[dict[str, str]],
    handler: Handler,
    *,
    dry_run: bool = False,
) -> ImportResult:
    """逐列跑匯入。dry_run 時走完全相同的路徑，只是最後整個退回。"""
    if dry_run:
        with dry_run_session(db) as scoped:
            result = _run(scoped, spec, rows, handler)
        result.dry_run = True
        return result
    return _run(db, spec, rows, handler)


def _sample(
    samples: list[RowResult],
    row_no: int,
    action: str,
    key: str | None,
    changed: list[str],
    message: str | None = None,
) -> None:
    if len(samples) < _SAMPLE_LIMIT:
        samples.append(
            RowResult(
                row=row_no, action=action, key=key, changed=changed, message=message
            )
        )


def _run(
    db: Any, spec: EntitySpec, rows: Iterable[dict[str, str]], handler: Handler
) -> ImportResult:
    fieldnames = getattr(rows, "fieldnames", None)
    rows = list(rows)
    header_error = _check_header(spec, rows, fieldnames)
    if header_error is not None:
        return ImportResult(
            imported=0,
            updated=0,
            skipped=0,
            errored=len(rows),
            errors=[header_error.message],
            error_groups=[header_error],
            total_rows=len(rows),
        )

    ctx = handler.preload(db)
    created = updated = skipped = errored = 0
    errors: list[tuple[int, str | None, str, str | None]] = []
    samples: list[RowResult] = []
    total = 0

    for row_no, row in enumerate(rows, start=2):
        total += 1
        key = _key_of(spec, row) or None
        # 每列一個 SAVEPOINT：Postgres 在語句失敗後會讓整個交易進入 aborted
        # 狀態，不退回 savepoint 的話後面每一列都會跟著失敗。
        nested = db.begin_nested()
        try:
            payload = handler.build(row, ctx)
            existing = handler.locate(db, row, ctx)
            if existing is None:
                handler.create(db, payload)
                created += 1
                action, changed = "create", []
            else:
                changed = handler.update(db, existing, payload)
                if changed:
                    updated += 1
                    action = "update"
                else:
                    skipped += 1
                    action = "skip"
            db.commit()
            _sample(samples, row_no, action, key, changed)
        except CellError as exc:
            # 失敗的 flush/commit 會把 nested transaction 留在 DEACTIVE，不是
            # INACTIVE：is_active 在那個狀態下是 False，若拿它當「要不要
            # rollback」的門檻，DEACTIVE 時就會整個跳過 rollback，session 卡在
            # 沒退回 SAVEPOINT 的狀態，下一列的 db.begin_nested() 直接拋
            # PendingRollbackError，讓 run_import 整批死掉——這正是 SAVEPOINT
            # 設計要防的事。rollback() 從 ACTIVE/DEACTIVE/PREPARED 都合法，
            # 一律呼叫，不看 is_active。
            nested.rollback()
            errored += 1
            errors.append((row_no, exc.field, exc.reason, exc.value))
            _sample(samples, row_no, "error", key, [], exc.reason)
        except PydanticValidationError as exc:
            nested.rollback()
            errored += 1
            # 一列可能同時炸出好幾個欄位的錯誤，但這仍然只是「一列失敗」——
            # errored 只加一次，不要跟著 sub_errors 的個數走，否則「錯誤 N」
            # 數的是欄位錯誤數，不是列數，跟「新增／更新／略過」三個列計數
            # 對不上（這正是本次要修的計數 bug）。
            sub_errors = _validation_errors(spec, exc)
            for field, reason, value in sub_errors:
                errors.append((row_no, field, reason, value))
            message = sub_errors[0][1] if sub_errors else "資料驗證失敗"
            _sample(samples, row_no, "error", key, [], message)
        except DomainError as exc:
            nested.rollback()
            errored += 1
            reason = str(exc)
            errors.append((row_no, None, reason, None))
            _sample(samples, row_no, "error", key, [], reason)
        except Exception as exc:  # noqa: BLE001 - 逐列回報，不中斷整批
            nested.rollback()
            errored += 1
            # 未知例外（如 DB 層的 IntegrityError）的 str(exc) 常常引用失敗的
            # 參數值，塞進 reason 會讓每一列訊息都不同，_group 收斂不起來，
            # 兩百列爛資料就是兩百組——固定成一句中文，原始文字改放進
            # sample_value，跟 CellError／_resolve_code 收斂的做法一致。
            reason = "該列寫入失敗"
            errors.append((row_no, None, reason, str(exc)))
            _sample(samples, row_no, "error", key, [], reason)

    groups = _group(errors)
    messages = [f"第 {n} 列：{reason}" for n, _, reason, _ in errors]
    if len(messages) > _ERROR_MSG_LIMIT:
        remaining = len(messages) - _ERROR_MSG_LIMIT
        messages = messages[:_ERROR_MSG_LIMIT]
        messages.append(f"…還有 {remaining} 則錯誤，詳見上方分組摘要。")
    return ImportResult(
        imported=created,
        updated=updated,
        skipped=skipped,
        errored=errored,
        errors=messages,
        error_groups=groups,
        sample_rows=samples,
        total_rows=total,
    )
