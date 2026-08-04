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
