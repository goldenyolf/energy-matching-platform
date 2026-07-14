"""Shared response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    detail: str


class ImportResult(BaseModel):
    """Result of a CSV / bulk import operation."""

    imported: int
    skipped: int = 0
    errors: list[str] = []
