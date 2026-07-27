"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.db.session import get_db

__all__ = ["get_db", "require_write_access"]


def require_write_access(
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Lightweight write gate: if an admin token is configured, create/update/
    delete requests must present a matching ``X-Admin-Token`` header. When no
    token is configured (local dev), writes are open."""
    token = settings.admin_write_token
    if token and x_admin_token != token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要編輯權限:請開啟編輯模式並輸入正確的密碼。",
        )
