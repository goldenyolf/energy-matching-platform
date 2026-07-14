"""FastAPI 應用程式：Energy Matching Platform API。

端點
====
- GET  /health              健康檢查
- GET  /dataset             取得目前使用的範例資料集
- GET  /match               以內建範例資料執行媒合並回傳分析
- POST /match               以使用者提供的資料集執行媒合
- GET  /companies/{id}      查詢單一企業的 RE 目標分析
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import __version__
from .data import load_sample_dataset
from .matching import match
from .models import Dataset, MatchingResult

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Energy Matching Platform",
    description="台灣綠電交易媒合 MVP：模擬風場、企業綠電合約與 RE 目標分析。",
    version=__version__,
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    """綠電媒合視覺化儀表板 (前端向 /match 取資料後渲染)。"""
    return (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """健康檢查。"""
    return {"status": "ok", "version": __version__}


@app.get("/dataset", response_model=Dataset, tags=["data"])
def get_dataset() -> Dataset:
    """回傳內建範例資料集。"""
    return load_sample_dataset()


@app.get("/match", response_model=MatchingResult, tags=["matching"])
def match_sample() -> MatchingResult:
    """以內建範例資料執行媒合並回傳完整分析。"""
    return match(load_sample_dataset())


@app.post("/match", response_model=MatchingResult, tags=["matching"])
def match_custom(dataset: Dataset) -> MatchingResult:
    """以使用者提供的資料集執行媒合。"""
    try:
        return match(dataset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/companies/{company_id}",
    tags=["matching"],
    summary="查詢單一企業的 RE 目標分析",
)
def company_analysis(company_id: str):
    """回傳指定企業在內建範例情境下的 RE 覆蓋率與缺口。"""
    result = match(load_sample_dataset())
    for company in result.company_results:
        if company.company_id == company_id:
            return company
    raise HTTPException(status_code=404, detail=f"找不到企業 {company_id}")
