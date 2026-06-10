"""Observed-state parsers for runtime infrastructure signals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from groundtruth.aidos.parsers import read_key_value_file
from groundtruth.aidos.schemas import ObservedState


def parse_observed_state(path_str: str) -> ObservedState:
    """Parse observed CLI/API exports into a normalized key/value view."""
    path = Path(path_str)
    payload: dict[str, Any] = read_key_value_file(path_str)
    return ObservedState(source=str(path), signals=payload)
