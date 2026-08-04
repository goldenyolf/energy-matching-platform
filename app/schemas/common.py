"""Shared response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    detail: str


class RowResult(BaseModel):
    """單列的處理結果。row 是 CSV 行號：標題列 = 1，資料首列 = 2。"""

    row: int
    action: Literal["create", "update", "skip", "error"]
    key: str | None = None
    changed: list[str] = []
    message: str | None = None


class ErrorGroup(BaseModel):
    """同一欄、同一種原因的錯誤收斂成一組。

    分組而非截斷：使用者要的不是兩千則一樣的訊息，而是「這一欄整欄格式錯了」。
    """

    field: str | None = None
    message: str
    count: int
    sample_rows: list[int] = []
    sample_value: str | None = None


class ImportResult(BaseModel):
    """Result of a CSV / bulk import operation."""

    imported: int
    skipped: int = 0
    errors: list[str] = []
    updated: int = 0
    error_groups: list[ErrorGroup] = []
    # 失敗的「列」數，不是失敗的「欄位」數：一列的 ValidationError 可能同時
    # 帶好幾個欄位錯誤，errors/error_groups 會展開成好幾筆，但使用者要看的
    # 「錯誤 N」跟「將略過 N 列」講的是列，這個欄位才是那個數字的真相來源。
    errored: int = 0
    sample_rows: list[RowResult] = []
    total_rows: int = 0
    dry_run: bool = False
