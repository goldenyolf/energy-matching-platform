"""合約詳情（商務視角）：把 12 次月度媒合的結果攤成一紙合約的履約與帳。

引擎（``app/matching/engine.py``）不改,本模組唯讀使用它的輸出。
"""

from __future__ import annotations

EPS = 1e-9

# 引擎 reason 字串裡的用語 → 本模組的約束代碼。
# 前三個來自有分配的情況,後三個來自 ``no allocation: …``——零分配時引擎也講了
# 原因,對應回去比一律歸類成「無」更有資訊。
_BINDING_WORDS = {
    "wind farm supply": "farm_supply",
    "customer demand": "customer_demand",
    "contract cap": "contract_cap",
    "wind farm has no remaining generation": "farm_supply",
    "customer consumption already fully covered": "customer_demand",
    "contract cap is zero": "contract_cap",
}

# 同時綁定多個約束時只挑一個上色與統計。案場供給用盡是最硬的限制——
# 調高合約上限也拿不到更多電,所以它排最前面;合約上限最軟,排最後。
_PRECEDENCE = ("farm_supply", "customer_demand", "contract_cap")


def classify_binding(reason: str) -> tuple[list[str], str]:
    """把引擎的 reason 字串拆成約束代碼清單與單一主約束。

    回傳的清單依 ``_PRECEDENCE`` 排序（穩定,不受 reason 字序影響）;
    認不出任何約束時回 ``([], "none")``。
    """
    found = {code for word, code in _BINDING_WORDS.items() if word in reason}
    ordered = [c for c in _PRECEDENCE if c in found]
    return (ordered, ordered[0]) if ordered else ([], "none")


def has_headroom(
    binding_primary: str, farm_unallocated_mwh: float, customer_unmet_mwh: float
) -> bool:
    """這個月有沒有「加購空間」。

    三個條件缺一不可：被合約上限卡住、案場還有餘電、客戶還有沒被滿足的用電。
    少了後兩者任一,「調高上限就能多拿」這句話就是假的——所以不能只看綁定約束。
    """
    return (
        binding_primary == "contract_cap"
        and farm_unallocated_mwh > EPS
        and customer_unmet_mwh > EPS
    )
