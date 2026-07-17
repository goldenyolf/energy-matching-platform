#!/bin/sh
# Render / container entrypoint for the Streamlit dashboard.
set -e
exec streamlit run dashboard/總覽.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
