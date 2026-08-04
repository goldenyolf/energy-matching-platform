"""_BaseHandler.update() 的邊界行為：不是 ORM 欄位的 payload key 要大聲失敗。

七個真正的 handler（見 test_import_schema.py 的
test_declared_columns_are_actually_consumed）已經證明 payload 的 key 永遠對得上
一個真正的 mapped column，所以這裡直接戳 _BaseHandler.update()，用一個假的
payload key 模擬「以後有人加了一個沒對應到欄位的 key」這種情境。
"""

from __future__ import annotations

import pytest

from app.ingestion.csv_importer import _BaseHandler
from app.models import WindFarm


def test_update_raises_loudly_for_a_payload_key_that_is_not_a_mapped_column(db):
    """getattr(existing, name, None) 的預設值會把「沒這個欄位」跟「欄位是
    None」混在一起：前者永遠 != 任何非 None 值，於是永遠被判定成「有變更」，
    setattr 建立一個 DB 根本沒有的幽靈屬性，之後每次重新匯入都白白報 update。
    """
    farm = WindFarm(code="WF-H1", name="H1", installed_capacity_mw=1.0)
    db.add(farm)
    db.commit()

    handler = _BaseHandler()
    with pytest.raises(ValueError, match="not_a_real_column"):
        handler.update(db, farm, {"not_a_real_column": "some value"})
