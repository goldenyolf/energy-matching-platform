"""Matching page — run the engine for a month and inspect the allocation."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Matching", page_icon="🔗", layout="wide")
st.title("🔗 Green Energy Matching")

period = st.sidebar.text_input("媒合月份 (YYYY-MM)", value="2024-01")

st.write(
    "選擇月份後執行媒合。演算法為 **deterministic**：同一份資料每次結果相同。"
    "分配依合約 priority、實際發電量與實際用電量計算，並保留每筆分配原因。"
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
st.subheader(f"媒合結果 · {run['period']} (run #{run['id']})")
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
    ]
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
        ],
        use_container_width=True,
    )

st.markdown("#### 未分配風電")
farms = pd.DataFrame(summary["wind_farms"])
if not farms.empty:
    st.dataframe(
        farms[["wind_farm_id", "generated_mwh", "allocated_mwh", "unallocated_mwh"]],
        use_container_width=True,
    )

skipped = summary.get("skipped_contracts", [])
if skipped:
    st.markdown("#### 未納入的合約（失效／尚未開始／非 active）")
    st.dataframe(pd.DataFrame(skipped), use_container_width=True)
