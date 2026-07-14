"""Energy Matching Platform — Streamlit dashboard (Overview page)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Energy Matching Platform", page_icon="⚡", layout="wide")


def period_selector() -> str:
    default = "2024-01"
    return st.sidebar.text_input("分析月份 (YYYY-MM)", value=default)


st.title("⚡ Energy Matching Platform")
st.caption(
    "台灣綠電交易媒合 MVP — 風場、企業綠電合約、綠電分配與 RE 目標分析。"
    "本平台資料為模擬資料，與任何能源公司無官方關係。"
)

# Backend connectivity
try:
    h = api.health()
    st.sidebar.success(f"後端連線正常 · v{h.get('version', '?')}")
except api.ApiError as exc:
    st.sidebar.error(str(exc))
    st.warning(
        "無法連線到後端 API。請先啟動：`uvicorn app.main:app --reload`，"
        "並確認 `API_BASE_URL` 設定正確。"
    )
    st.stop()

period = period_selector()

try:
    summary = api.analytics_summary(period)
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

st.subheader(f"平台總覽 · {period}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("總發電量 (MWh)", f"{summary['total_generation_mwh']:,.0f}")
c2.metric("已分配 (MWh)", f"{summary['total_allocated_mwh']:,.0f}")
c3.metric("未分配 (MWh)", f"{summary['total_unallocated_mwh']:,.0f}")
c4.metric("平均 RE 達成率", f"{summary['average_re_percent']:.1f}%")

c5, c6, c7 = st.columns(3)
c5.metric("客戶數", summary["customer_count"])
c6.metric("風場數", summary["wind_farm_count"])
c7.metric(
    "達標客戶", f"{summary['customers_meeting_target']} / {summary['customer_count']}"
)

st.divider()

col_left, col_right = st.columns(2)
with col_left:
    st.markdown("#### 各客戶 RE 達成率 (%)")
    customers = api.analytics_customers(period)
    if customers:
        df = pd.DataFrame(customers).set_index("company_name")
        st.bar_chart(df[["achieved_re_percent", "re_target_percent"]])
with col_right:
    st.markdown("#### 各風場利用率 (%)")
    farms = api.analytics_wind_farms(period)
    if farms:
        df = pd.DataFrame(farms).set_index("name")
        st.bar_chart(df[["utilization_percent"]])

st.info(
    "使用左側頁面切換到 Wind Farms / Customers / Contracts / Matching。"
    "若尚未載入資料，請先執行 `make seed`。"
)
