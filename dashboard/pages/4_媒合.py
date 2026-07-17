"""媒合頁面 — 對某月執行媒合引擎並檢視分配結果。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="媒合", page_icon="🔗", layout="wide")
st.title("🔗 綠電媒合")

period = st.sidebar.text_input("媒合月份 (YYYY-MM)", value="2024-01")

st.write(
    "選擇月份後執行媒合。演算法為**決定性(deterministic)**:同一份資料每次結果相同。"
    "分配依合約優先序(priority)、實際發電量與實際用電量計算,並保留每筆分配原因。"
)

if st.button("▶ 執行媒合", type="primary"):
    try:
        run = api.run_matching(period)
    except api.ApiError as exc:
        st.error(str(exc))
        st.stop()
    st.session_state["run"] = run

run = st.session_state.get("run")
if not run:
    st.info("尚未執行。點擊上方按鈕開始媒合。")
    st.stop()

summary = run["result_summary"]
st.subheader(f"媒合結果 · {run['period']}(媒合 #{run['id']})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("總發電 (MWh)", f"{summary['total_generation_mwh']:,.0f}")
c2.metric("已分配 (MWh)", f"{summary['total_allocated_mwh']:,.0f}")
c3.metric("未分配 (MWh)", f"{summary['total_unallocated_mwh']:,.0f}")
c4.metric("達標客戶", f"{summary['customers_meeting_target']}")

st.markdown("#### 分配明細與原因")
results = run.get("results", [])
if results:
    df = pd.DataFrame(results)[
        [
            "contract_id",
            "wind_farm_id",
            "customer_id",
            "allocated_energy_mwh",
            "achieved_re_percent",
            "allocation_reason",
        ]
    ].rename(
        columns={
            "contract_id": "合約 ID",
            "wind_farm_id": "風場 ID",
            "customer_id": "客戶 ID",
            "allocated_energy_mwh": "已分配 (MWh)",
            "achieved_re_percent": "RE 達成率 (%)",
            "allocation_reason": "分配原因",
        }
    )
    st.dataframe(df, use_container_width=True)

st.markdown("#### 客戶綠電缺口")
cust = pd.DataFrame(summary["customers"])
if not cust.empty:
    st.dataframe(
        cust[
            [
                "customer_id",
                "consumption_mwh",
                "allocated_mwh",
                "achieved_re_percent",
                "gap_to_target_mwh",
                "target_met",
            ]
        ].rename(
            columns={
                "customer_id": "客戶 ID",
                "consumption_mwh": "用電量 (MWh)",
                "allocated_mwh": "已分配 (MWh)",
                "achieved_re_percent": "RE 達成率 (%)",
                "gap_to_target_mwh": "目標缺口 (MWh)",
                "target_met": "是否達標",
            }
        ),
        use_container_width=True,
    )

st.markdown("#### 未分配風電")
farms = pd.DataFrame(summary["wind_farms"])
if not farms.empty:
    st.dataframe(
        farms[
            ["wind_farm_id", "generated_mwh", "allocated_mwh", "unallocated_mwh"]
        ].rename(
            columns={
                "wind_farm_id": "風場 ID",
                "generated_mwh": "發電量 (MWh)",
                "allocated_mwh": "已分配 (MWh)",
                "unallocated_mwh": "未分配 (MWh)",
            }
        ),
        use_container_width=True,
    )

skipped = summary.get("skipped_contracts", [])
if skipped:
    st.markdown("#### 未納入的合約(已失效／尚未開始／非啟用中)")
    st.dataframe(
        pd.DataFrame(skipped).rename(
            columns={
                "contract_id": "合約 ID",
                "contract_number": "合約編號",
                "reason": "原因",
            }
        ),
        use_container_width=True,
    )
