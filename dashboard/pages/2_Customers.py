"""Customers page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Customers", page_icon="🏢", layout="wide")
st.title("🏢 Customers")

period = st.sidebar.text_input("分析月份 (YYYY-MM)", value="2024-01")

try:
    customers = api.customers()
    analytics = api.analytics_customers(period)
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not customers:
    st.info("尚無客戶資料，請先執行 `make seed`。")
    st.stop()

st.subheader("客戶基本資料")
st.dataframe(
    pd.DataFrame(customers)[
        [
            "code",
            "company_name",
            "industry",
            "annual_consumption_mwh",
            "re_target_percent",
            "target_year",
        ]
    ],
    use_container_width=True,
)

st.subheader(f"RE 目標達成分析 · {period}")
if analytics:
    df = pd.DataFrame(analytics)
    show = df[
        [
            "company_name",
            "consumption_mwh",
            "allocated_mwh",
            "achieved_re_percent",
            "re_target_percent",
            "gap_to_target_mwh",
            "target_met",
        ]
    ]
    st.dataframe(show, use_container_width=True)
    st.markdown("#### 綠電覆蓋率 vs. RE 目標 (%)")
    st.bar_chart(
        df.set_index("company_name")[["achieved_re_percent", "re_target_percent"]]
    )
    st.markdown("#### 距離 RE 目標的缺口 (MWh)")
    st.bar_chart(df.set_index("company_name")[["gap_to_target_mwh"]])
