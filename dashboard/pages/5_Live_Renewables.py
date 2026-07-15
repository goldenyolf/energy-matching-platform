"""Live Renewables page — Taipower real-time instantaneous MW."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="Live Renewables", page_icon="⚡", layout="wide")
st.title("⚡ 台電即時再生能源")
st.caption(
    "資料來源:台電各機組即時發電量(約每 10 分鐘更新)。"
    "此為瞬時 MW 快照,非月度能量,不進媒合。"
)

force = st.button("🔄 重新整理(略過快取)")

try:
    data = api.live_renewables(force=force)
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

st.metric("快照時間", data.get("snapshot_time") or "—")
col1, col2 = st.columns(2)
col1.metric("風力總出力 (MW)", f"{data['wind_total_mw']:,.1f}")
col2.metric("再生能源總出力 (MW)", f"{data['renewable_total_mw']:,.1f}")

st.subheader("各再生能源類型即時出力")
summary = pd.DataFrame(data["renewable_summary"])
if not summary.empty:
    st.bar_chart(summary.set_index("unit_type")["net_mw"])
    st.dataframe(summary, use_container_width=True)

st.subheader("風力各機組即時出力")
wind = pd.DataFrame(data["wind"])
if not wind.empty:
    st.dataframe(
        wind.rename(
            columns={
                "name": "機組名稱",
                "capacity_mw": "裝置容量(MW)",
                "net_mw": "淨發電量(MW)",
            }
        ),
        use_container_width=True,
    )
else:
    st.info("目前無風力機組資料。")
