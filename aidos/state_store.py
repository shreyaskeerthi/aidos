"""Persistent JSON state stores for AIDOS runtime state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStateStore:
    """Simple file-backed JSON document store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
