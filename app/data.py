"""範例資料載入工具。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import Dataset

# 專案根目錄下的 data/sample_data.json
_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_data.json"


def load_dataset(path: str | Path | None = None) -> Dataset:
    """從 JSON 檔載入並驗證資料集。"""
    file_path = Path(path) if path is not None else _DATA_FILE
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return Dataset.model_validate(raw)


@lru_cache(maxsize=1)
def load_sample_dataset() -> Dataset:
    """載入內建範例資料 (快取)。"""
    return load_dataset(_DATA_FILE)
