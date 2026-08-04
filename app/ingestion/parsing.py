"""Small, forgiving value parsers for CSV cells."""

from __future__ import annotations

from datetime import date, datetime

from app.ingestion.schema import Column


def s(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def f(value: str | None) -> float | None:
    v = s(value)
    return None if v is None else float(v)


def i(value: str | None) -> int | None:
    v = s(value)
    return None if v is None else int(v)


def d(value: str | None) -> date | None:
    v = s(value)
    if v is None:
        return None
    return datetime.strptime(v, "%Y-%m-%d").date()


class CellError(Exception):
    """單一儲存格解析失敗，帶得走欄位與原值。"""

    def __init__(self, field: str, label: str, value: str, reason: str) -> None:
        super().__init__(reason)
        self.field = field
        self.label = label
        self.value = value
        self.reason = reason


def parse_cell(column: Column, raw: str | None) -> object:
    """依欄位型別解析，失敗時丟出帶中文原因的 CellError。"""
    text = s(raw)
    if text is None:
        if column.required:
            raise CellError(
                column.name, column.label, "", f"{column.label}為必填，不可空白"
            )
        return None
    try:
        if column.kind == "float":
            return float(text)
        if column.kind == "int":
            return int(text)
        if column.kind == "date":
            return d(text)
        if column.kind == "shares":
            return [float(x) for x in text.split(";")]
        return text
    except CellError:
        raise
    except ValueError as exc:
        raise CellError(column.name, column.label, text, _reason(column, text)) from exc


def _reason(column: Column, text: str) -> str:
    if column.kind in ("float", "int"):
        return f"{column.label}「{text}」不是數字"
    if column.kind == "date":
        return f"{column.label}「{text}」不是有效日期，格式須為 YYYY-MM-DD"
    if column.kind == "shares":
        return f"{column.label}「{text}」格式錯誤，須為以分號隔開的數字"
    return f"{column.label}「{text}」無效"
