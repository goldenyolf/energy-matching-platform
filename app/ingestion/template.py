"""由欄位表產生 CSV 範本。"""

from __future__ import annotations

import csv
import io

from app.ingestion.schema import EntitySpec

# Excel 需要 BOM 才會把 UTF-8 中文正確解讀；parse_csv() 用 utf-8-sig 解碼，
# 所以下載下來的範本可以原封不動匯回去。
_BOM = b"\xef\xbb\xbf"


def build_csv(spec: EntitySpec) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(spec.column_names())
    writer.writerow([c.example for c in spec.columns])
    return _BOM + buf.getvalue().encode("utf-8")
