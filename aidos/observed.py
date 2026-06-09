"""Observed-state parsers for runtime infrastructure signals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aidos.parsers import read_key_value_file
from aidos.schemas import ObservedState


def _normalize_pyats_signals(payload: dict[str, Any]) -> dict[str, Any]:
    devices = payload.get("devices")
    if not isinstance(devices, dict):
        return payload

    failed_commands: list[dict[str, str]] = []
    command_count = 0
    for device_name, results in devices.items():
        if not isinstance(results, dict):
            continue
        for command, detail in results.items():
            command_count += 1
            if isinstance(detail, dict) and detail.get("mode") == "error":
                failed_commands.append(
                    {
                        "device": str(device_name),
                        "command": str(command),
                        "error": str(detail.get("error", "unknown error")),
                    }
                )

    return {
        **payload,
        "pyats_device_count": len(devices),
        "pyats_command_count": command_count,
        "pyats_failed_commands": failed_commands,
    }


def parse_observed_state(path_str: str) -> ObservedState:
    """Parse observed CLI/API exports into a normalized key/value view."""
    path = Path(path_str)
    payload: dict[str, Any] = read_key_value_file(path_str)
    signals = _normalize_pyats_signals(payload)
    return ObservedState(source=str(path), signals=signals)
