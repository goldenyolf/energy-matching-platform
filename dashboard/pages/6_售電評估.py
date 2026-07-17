"""Sales Evaluation page — seller margin + buyer RE%/cost (like the reference deck)."""

from __future__ import annotations

import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="售電評估", page_icon="📈", layout="wide")
st.title("📈 售電評估")

try:
    customers = api.customers()
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not customers:
    st.info("尚無客戶資料,請先執行 seed。")
    st.stop()

by_label = {f"{c['code']} · {c['company_name']}": c for c in customers}
label = st.sidebar.selectbox("用電戶", list(by_label))
start = st.sidebar.text_input("起始月 (YYYY-MM,可空)", value="")
end = st.sidebar.text_input("結束月 (YYYY-MM,可空)", value="")
chosen = by_label[label]

try:
    r = api.evaluation(chosen["id"], start=start or None, end=end or None)
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

st.caption(f"{r['customer_code']} · {r['company_name']} · {r['start']} ~ {r['end']}")
if r["used_default_feed_in_price"]:
    st.warning("部分風場未填收購價,已用預設值估算。")

seller, buyer = st.columns(2)
with seller:
    st.subheader("售電端")
    st.metric("收購成本 (NTD)", f"{r['seller']['procurement_cost']:,.0f}")
    st.metric("售電收入 (NTD)", f"{r['seller']['sales_revenue']:,.0f}")
    st.metric(
        "售電毛利 (NTD)",
        f"{r['seller']['gross_profit']:,.0f}",
        delta=f"{r['seller']['gross_margin_percent']:.2f}%",
    )
with buyer:
    st.subheader("用電端")
    st.metric("RE 比例", f"{r['buyer']['re_percent']:.2f}%")
    st.metric(
        "綠電 / 灰電 (MWh)",
        f"{r['buyer']['green_mwh']:,.1f} / {r['buyer']['grey_mwh']:,.1f}",
    )
    st.metric("用電平均單價 (NTD/kWh)", f"{r['buyer']['avg_price_per_kwh']:.4f}")
    st.metric("增加用電成本 (NTD)", f"{r['buyer']['added_cost']:,.0f}")
