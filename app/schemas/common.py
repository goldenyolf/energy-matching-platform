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
    sample_rows: list[RowResult] = []
    total_rows: int = 0
    dry_run: bool = False
