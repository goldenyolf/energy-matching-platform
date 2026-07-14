"""Wind Farms page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Wind Farms", page_icon="🌬️", layout="wide")
st.title("🌬️ Wind Farms")

period = st.sidebar.text_input("分析月份 (YYYY-MM)", value="2024-01")

try:
    farms = api.wind_farms()
    analytics = {a["wind_farm_id"]: a for a in api.analytics_wind_farms(period)}
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not farms:
    st.info("尚無風場資料，請先執行 `make seed`。")
    st.stop()

st.subheader("風場基本資料")
st.dataframe(
    pd.DataFrame(farms)[
        [
            "code",
            "name",
            "operator_name",
            "location",
            "installed_capacity_mw",
            "commercial_operation_date",
            "status",
        ]
    ],
    use_container_width=True,
)

st.subheader(f"月度發電與分配 · {period}")
rows = []
for f in farms:
    a = analytics.get(f["id"], {})
    rows.append(
        {
            "code": f["code"],
            "name": f["name"],
            "generated_mwh": a.get("generated_mwh", 0),
            "allocated_mwh": a.get("allocated_mwh", 0),
            "unallocated_mwh": a.get("unallocated_mwh", 0),
            "utilization_percent": a.get("utilization_percent", 0),
        }
    )
df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True)
st.bar_chart(df.set_index("name")[["allocated_mwh", "unallocated_mwh"]])

with st.expander("查看某風場的逐月發電資料"):
    codes = {f["code"]: f["id"] for f in farms}
    chosen = st.selectbox("選擇風場", list(codes))
    gen = api.generation(codes[chosen])
    if gen:
        g = pd.DataFrame(gen)[["period_start", "generated_energy_mwh", "data_source"]]
        st.dataframe(g, use_container_width=True)
