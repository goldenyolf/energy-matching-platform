"""每列一個 SAVEPOINT 的整個理由：DB 層失敗只該賠掉那一列，不是整批。

Handler 出的錯（CellError／DomainError／pydantic ValidationError）都攔在 Python
層，不會真的碰到 flush/commit。這裡刻意繞過那些關卡，直接讓中間一列在
flush/commit 時炸出一個 SQLAlchemy IntegrityError——這是唯一真正驗證
「失敗的 SAVEPOINT 有沒有正確退回」的方式。
"""

from __future__ import annotations

from app.ingestion import pipeline
from app.ingestion.schema import SPECS
from app.models import WindFarm


class _FlakyFarmHandler:
    """中間那列故意繞過 pydantic，直接送一個違反 NOT NULL 的 ORM 物件——
    製造 parse_cell／DomainError／ValidationError 都攔不到的資料庫層失敗。"""

    spec = SPECS["farm"]

    def preload(self, db):
        return {}

    def build(self, row, ctx):
        return dict(row)

    def locate(self, db, row, ctx):
        return None

    def create(self, db, payload):
        code = payload["code"]
        if code == "BAD":
            db.add(WindFarm(code=code))  # 缺 name／installed_capacity_mw → NOT NULL
        else:
            db.add(WindFarm(code=code, name=code, installed_capacity_mw=1.0))
        db.commit()

    def update(self, db, existing, payload):
        return []


def _row(code: str) -> dict[str, str]:
    # name/installed_capacity_mw only need to be present for the header check;
    # _FlakyFarmHandler.create() ignores their values entirely.
    return {"code": code, "name": code, "installed_capacity_mw": "1"}


def test_a_db_level_failure_mid_batch_does_not_kill_the_rest_of_the_batch(db):
    rows = [_row("A"), _row("BAD"), _row("C")]

    result = pipeline.run_import(db, SPECS["farm"], rows, _FlakyFarmHandler())

    assert result.imported == 2
    assert len(result.errors) == 1
    persisted = {f.code for f in db.query(WindFarm).all()}
    assert persisted == {"A", "C"}


def test_two_db_level_failures_in_a_row_still_do_not_kill_the_batch(db):
    """單一失敗後 nested transaction 卡死是一回事，連續兩個失敗會再更明顯——
    第二個失敗發生時，若第一次的 rollback 沒真的退回，
    ``db.begin_nested()`` 會直接拋 PendingRollbackError，這個測試就會整個炸掉
    而不是回傳一個 ImportResult。
    """
    rows = [_row("BAD"), _row("BAD"), _row("C")]

    result = pipeline.run_import(db, SPECS["farm"], rows, _FlakyFarmHandler())

    assert result.imported == 1
    assert len(result.errors) == 2
    assert {f.code for f in db.query(WindFarm).all()} == {"C"}


def test_generic_db_failures_collapse_to_one_chinese_group_not_one_per_row(db):
    """IntegrityError 的 str(exc) 常常引用失敗的參數（含原值），如果那段英文
    原封不動塞進 reason，_group 就收斂不起來——兩百列同一種資料庫層失敗會
    變成兩百組，而不是設計要的『種類數決定 payload 大小』。這裡用 60 列同一種
    NOT NULL 失敗驗證：全部收斂成一組、reason 是固定中文、原始例外文字改放
    進 sample_value。``locate()`` 在這個假 handler 裡永遠回傳 ``None``，所以
    60 列同樣的 code 都會走 create 路徑，不會被誤判成 upsert。"""
    rows = [_row("BAD") for _ in range(60)]

    result = pipeline.run_import(db, SPECS["farm"], rows, _FlakyFarmHandler())

    assert result.imported == 0
    assert result.errored == 60
    assert len(result.error_groups) == 1
    group = result.error_groups[0]
    assert group.count == 60
    assert group.message == "該列寫入失敗"
    assert group.sample_value is not None and "wind_farms" in group.sample_value

    # errors 是保留給舊呼叫端的扁平清單，容量必須有上限：60 則不該原封不動地
    # 全部塞進去，一份全壞的大檔案不該讓這個欄位的 payload 跟著壞列數線性成長。
    assert len(result.errors) <= 51
    assert "還有" in result.errors[-1]
