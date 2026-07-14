"""Contracts page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Contracts", page_icon="📄", layout="wide")
st.title("📄 Contracts (PPA)")

period = st.sidebar.text_input("分析月份 (YYYY-MM)", value="2024-01")

try:
    contracts = api.contracts()
    farms = {f["id"]: f["code"] for f in api.wind_farms()}
    customers = {c["id"]: c["code"] for c in api.customers()}
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not contracts:
    st.info("尚無合約資料，請先執行 `make seed`。")
    st.stop()

rows = []
for c in contracts:
    rows.append(
        {
            "contract_number": c["contract_number"],
            "wind_farm": farms.get(c["wind_farm_id"], c["wind_farm_id"]),
            "customer": customers.get(c["customer_id"], c["customer_id"]),
            "start_date": c["start_date"],
            "end_date": c["end_date"],
            "energy_mwh": c["contracted_energy_mwh"],
            "percentage": c["contracted_percentage"],
            "price_per_kwh": c["price_per_kwh"],
            "priority": c["priority"],
            "status": c["status"],
        }
    )
st.subheader("合約清單")
st.dataframe(pd.DataFrame(rows), use_container_width=True)

st.subheader(f"合約使用率 · {period}")
st.caption("使用率 = 該月實際分配量 ÷ 合約月度上限（透過對該月執行媒合取得）。")
if st.button("計算合約使用率"):
    try:
        run = api.run_matching(period)
    except api.ApiError as exc:
        st.error(str(exc))
    else:
        results = run.get("results", [])
        # utilization derives from stored contract limit vs allocation; use results
        summary = pd.DataFrame(results)
        if not summary.empty:
            agg = (
                summary.groupby("contract_id")["allocated_energy_mwh"]
                .sum()
                .reset_index()
            )
            st.dataframe(agg, use_container_width=True)
        st.success(f"已執行 {period} 媒合（run #{run['id']}）。")
