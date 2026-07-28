"""Minimal structured logging setup.

Configures a single stream handler with a compact, timestamped format so the
app's logs are legible in Render's log stream. Idempotent: safe to call once at
import time. This is intentionally lightweight — a real deployment can layer a
JSON formatter or an error-tracking handler (Sentry) on top.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str = "app") -> logging.Logger:
    return logging.getLogger(name)
