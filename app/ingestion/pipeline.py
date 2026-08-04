"""共用匯入管線：dry-run 隔離與逐列執行骨架。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import DomainError
from app.ingestion.parsing import CellError
from app.ingestion.schema import EntitySpec
from app.schemas.common import ErrorGroup, ImportResult, RowResult

# 成功列只回樣本：確認欄位有對上不需要看一萬列。
_SAMPLE_LIMIT = 20
# 每組錯誤附幾個列號，讓使用者找得到但不洗版。
_GROUP_ROWS = 10


@contextmanager
def dry_run_session(db: Session) -> Iterator[Session]:
    """在外層 session 自己的連線上開一個 SAVEPOINT，離開時退回。

    綁在同一條連線是刻意的：測試用 ``sqlite://`` ＋ ``StaticPool``，整個
    engine 共用一條 DBAPI 連線，另開連線會撞上「cannot start a transaction
    within a transaction」。``join_transaction_mode="create_savepoint"`` 讓
    ``BaseRepository.create()`` 內部的 ``commit()`` 只是釋放 SAVEPOINT，
    外層不受影響——所以 dry-run 走的是與真匯入完全相同的寫入路徑。
    """
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
    """依 (欄位, 原因) 收斂。payload 大小由錯誤的種類數決定，不由列數決定。"""
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


def _check_header(spec: EntitySpec, rows: list[dict[str, str]]) -> ErrorGroup | None:
    """缺必填欄是整檔的問題。逐列報一千次只會把真正的訊息淹掉。"""
    if not rows:
        return None
    present = set(rows[0])
    missing = [c for c in spec.required_names() if c not in present]
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


def _run(
    db: Any, spec: EntitySpec, rows: Iterable[dict[str, str]], handler: Handler
) -> ImportResult:
    rows = list(rows)
    header_error = _check_header(spec, rows)
    if header_error is not None:
        return ImportResult(
            imported=0,
            updated=0,
            skipped=0,
            errors=[header_error.message],
            error_groups=[header_error],
            total_rows=len(rows),
        )

    ctx = handler.preload(db)
    created = updated = skipped = 0
    errors: list[tuple[int, str | None, str, str | None]] = []
    samples: list[RowResult] = []
    total = 0

    for row_no, row in enumerate(rows, start=2):
        total += 1
        key = _key_of(spec, row)
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
            if len(samples) < _SAMPLE_LIMIT:
                samples.append(
                    RowResult(
                        row=row_no, action=action, key=key or None, changed=changed
                    )
                )
        except CellError as exc:
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, exc.field, exc.reason, exc.value))
        except DomainError as exc:
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, None, str(exc), None))
        except Exception as exc:  # noqa: BLE001 - 逐列回報，不中斷整批
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, None, str(exc), None))

    groups = _group(errors)
    return ImportResult(
        imported=created,
        updated=updated,
        skipped=skipped,
        errors=[f"row {n}: {reason}" for n, _, reason, _ in errors],
        error_groups=groups,
        sample_rows=samples,
        total_rows=total,
    )
