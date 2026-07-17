"""時段媒合:台電三段式時間電價逐時段媒合與時段別經濟。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="時段媒合", page_icon="⏱️", layout="wide")
st.title("⏱️ 時段時間電價媒合(P4a)")
st.caption(
    "台電三段式時間電價(尖峰/半尖峰/離峰 × 夏月/非夏月)逐時段媒合。"
    "RE 跨時段加總;用電端成本用逐時段灰電價,凸顯尖峰綠電的較高價值。"
)

period = st.text_input("期間 (YYYY-MM)", value="2024-01")

if st.button("執行時段媒合", type="primary"):
    try:
        r = api.slot_matching(period)
    except api.ApiError as exc:
        st.error(str(exc))
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("季別", "夏月" if r["season"] == "summer" else "非夏月")
    m2.metric("售電端總毛利 (NTD)", f"{r['seller_gross_margin_ntd']:,.0f}")
    m3.metric("用電端 RE", f"{r['buyer']['re_percent']:.2f}%")

    st.markdown("#### 各客戶 RE 達成(跨時段)")
    st.dataframe(
        pd.DataFrame(r["customer_summaries"]).rename(
            columns={
                "customer_id": "客戶 ID",
                "consumption_mwh": "用電量 (MWh)",
                "allocated_mwh": "已分配 (MWh)",
                "achieved_re_percent": "RE 達成率 (%)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 時段別明細")
    for sub in r["slot_breakdown"]:
        label = {"peak": "尖峰", "half_peak": "半尖峰", "off_peak": "離峰"}[sub["slot"]]
        st.markdown(f"**{label}** · 灰電價 {sub['grey_price_per_kwh']} NTD/kWh")
        st.dataframe(
            pd.DataFrame(sub["customer_summaries"]).rename(
                columns={
                    "customer_id": "客戶 ID",
                    "consumption_mwh": "用電量 (MWh)",
                    "allocated_mwh": "已分配 (MWh)",
                    "achieved_re_percent": "RE 達成率 (%)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### 分配明細(逐時段)")
    st.dataframe(
        pd.DataFrame(r["allocations"]).rename(
            columns={
                "contract_number": "合約編號",
                "wind_farm_id": "風場 ID",
                "customer_id": "客戶 ID",
                "slot": "時段",
                "allocated_mwh": "已分配 (MWh)",
                "reason": "分配原因",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
