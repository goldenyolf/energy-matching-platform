"""最佳化媒合:全域經濟最佳化,並與優先序引擎並列對比。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="最佳化媒合", page_icon="🎯", layout="wide")
st.title("🎯 經濟最佳化媒合(P3)")
st.caption(
    "以 MILP 全域最佳化:目標為售電端毛利最大,RE 目標為硬約束(不可行時退為軟約束),"
    "並支援「最少案場數 / 最小分配%」結構約束。"
)

col_a, col_b, col_c = st.columns(3)
period = col_a.text_input("期間 (YYYY-MM)", value="2024-01")
min_sites = col_b.number_input(
    "最少案場數 / 客戶", min_value=0, max_value=10, value=0, step=1
)
min_pct = col_c.number_input(
    "最小分配% (佔客戶用電)", min_value=0.0, max_value=100.0, value=0.0, step=1.0
)

if st.button("執行最佳化", type="primary"):
    try:
        opt = api.optimize(
            period,
            min_sites=int(min_sites) or None,
            min_site_allocation_percent=float(min_pct) or None,
        )
    except api.ApiError as exc:
        st.error(str(exc))
        st.stop()

    st.subheader("求解結果")
    m1, m2 = st.columns(2)
    m1.metric("售電端總毛利 (NTD)", f"{opt['objective_gross_margin_ntd']:,.0f}")
    m2.metric("求解狀態", opt["solver_status"])

    targets = opt["customer_targets"]
    if targets:
        st.markdown("**各客戶 RE 目標達成**")
        st.dataframe(
            pd.DataFrame(targets).rename(
                columns={
                    "customer_id": "客戶ID",
                    "re_target_mwh": "RE目標(MWh)",
                    "allocated_mwh": "分配(MWh)",
                    "re_shortfall_mwh": "缺口(MWh)",
                    "re_target_met": "達標",
                    "sites_used": "使用案場數",
                    "site_shortfall": "案場缺口",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("**分配明細**")
    st.dataframe(
        pd.DataFrame(opt["allocations"]),
        use_container_width=True,
        hide_index=True,
    )

    # ---- 並列對比:優先序引擎 ----
    st.subheader("策略對比:優先序 vs 最佳化")
    try:
        run = api.run_matching(period)
        summary = run.get("result_summary", {}) or {}
        greedy_re = summary.get("average_re_percent", 0.0)
        greedy_alloc = summary.get("total_allocated_mwh", 0.0)
    except api.ApiError as exc:
        st.info(f"無法取得優先序對比:{exc}")
        greedy_re = greedy_alloc = None

    opt_alloc = sum(a["allocated_mwh"] for a in opt["allocations"])
    opt_avg_re = (
        sum(t["allocated_mwh"] for t in targets)
        / sum(s["consumption_mwh"] for s in opt["customer_summaries"])
        * 100.0
        if opt["customer_summaries"]
        and sum(s["consumption_mwh"] for s in opt["customer_summaries"]) > 0
        else 0.0
    )
    compare = pd.DataFrame(
        [
            {
                "策略": "優先序 (greedy)",
                "總分配 (MWh)": greedy_alloc,
                "平均 RE %": greedy_re,
            },
            {
                "策略": "全域最佳化 (MILP)",
                "總分配 (MWh)": round(opt_alloc, 3),
                "平均 RE %": round(opt_avg_re, 3),
            },
        ]
    )
    st.dataframe(compare, use_container_width=True, hide_index=True)
    st.caption(
        "最佳化以毛利為目標並保證 RE 硬約束,優先序則依合約 priority;兩者分配策略不同。"
    )
