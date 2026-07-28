"""Shared API dependencies."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, UploadFile, status

from app.core.config import settings
from app.db.session import get_db

__all__ = ["get_db", "read_upload", "require_write_access"]

# Cap CSV uploads so a hostile/oversized file can't exhaust memory.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB


def require_write_access(
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Lightweight write gate: if an admin token is configured, create/update/
    delete requests must present a matching ``X-Admin-Token`` header. When no
    token is configured (local dev), writes are open."""
    token = settings.admin_write_token
    if token and not hmac.compare_digest(x_admin_token or "", token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要編輯權限:請開啟編輯模式並輸入正確的密碼。",
        )


async def read_upload(file: UploadFile) -> bytes:
    """Read an uploaded file, rejecting anything over ``MAX_UPLOAD_BYTES``."""
    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"檔案過大,上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB。",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"檔案過大,上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB。",
        )
    return content
