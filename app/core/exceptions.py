"""Domain exceptions, mapped to HTTP status codes in the API layer."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected, client-facing errors."""


class NotFoundError(DomainError):
    """Requested resource does not exist (→ 404)."""


class ConflictError(DomainError):
    """Uniqueness or state conflict (→ 409)."""


class ValidationError(DomainError):
    """Business-rule validation failure (→ 422)."""
