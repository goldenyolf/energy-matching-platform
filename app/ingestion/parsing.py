"""Small, forgiving value parsers for CSV cells."""

from __future__ import annotations

from datetime import date, datetime


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
