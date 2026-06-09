"""Structured logging helpers for AIDOS services."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


def get_logger(name: str) -> logging.Logger:
    """Return logger configured for JSON-line structured events."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured JSON log event."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    logger.info(json.dumps(payload, default=str))
