from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1", "on"}:
        return True
    if text in {"no", "n", "false", "0", "off"}:
        return False
    return None


def _parse_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        if "." in str(value):
            return float(value)
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    key_map = {
        "loading dock": "loading_dock",
        "server lift": "server_lift",
        "rack floor psf": "rack_floor_psf",
        "rack psf": "rack_floor_psf",
        "liquid cooling": "liquid_cooling",
        "power": "power",
        "available circuits": "available_circuits",
        "uplinks": "uplinks",
        "40g ports": "ports_40g",
        "ports 40g": "ports_40g",
        "vlan config needed": "vlan_config_needed",
        "network diagram provided": "network_diagram_provided",
        "layout blueprint provided": "layout_blueprint_provided",
        "gpu model": "gpu_model",
        "node count": "node_count",
        "target platform": "target_platform",
        "vlan ids": "vlan_ids",
    }

    normalized: dict[str, Any] = {}
    for raw_key, value in record.items():
        clean_key = str(raw_key).strip().lower().replace("_", " ")
        canonical = key_map.get(clean_key, clean_key.replace(" ", "_"))
        normalized[canonical] = value

    for bool_key in [
        "loading_dock",
        "server_lift",
        "liquid_cooling",
        "available_circuits",
        "ports_40g",
        "vlan_config_needed",
        "network_diagram_provided",
        "layout_blueprint_provided",
    ]:
        if bool_key in normalized:
            parsed = _parse_bool(normalized[bool_key])
            normalized[bool_key] = normalized[bool_key] if parsed is None else parsed

    for numeric_key in ["rack_floor_psf", "node_count"]:
        if numeric_key in normalized:
            parsed = _parse_number(normalized[numeric_key])
            normalized[numeric_key] = normalized[numeric_key] if parsed is None else parsed

    if isinstance(normalized.get("vlan_ids"), str):
        normalized["vlan_ids"] = [
            item.strip() for item in normalized["vlan_ids"].split(",") if item.strip()
        ]

    return normalized


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object.")
    return payload


def _read_csv(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))

    if rows:
        return rows[0]

    key_value: dict[str, Any] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) >= 2:
                key_value[row[0]] = row[1]
    return key_value


def _read_xlsx(path: Path) -> dict[str, Any]:
    import pandas as pd

    workbook = pd.read_excel(path, sheet_name=None)
    for _, frame in workbook.items():
        if frame.empty:
            continue

        cols = [str(col).strip().lower() for col in frame.columns]
        if {"field", "value"}.issubset(set(cols)):
            key_col = frame.columns[cols.index("field")]
            value_col = frame.columns[cols.index("value")]
            return {
                str(row[key_col]).strip(): row[value_col]
                for _, row in frame.iterrows()
                if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
            }

        if len(frame.columns) >= 2:
            key_col = frame.columns[0]
            value_col = frame.columns[1]
            key_value = {
                str(row[key_col]).strip(): row[value_col]
                for _, row in frame.iterrows()
                if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
            }
            if key_value:
                return key_value

    return {}


def read_input(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _normalize_record(_read_json(path))
    if suffix == ".csv":
        return _normalize_record(_read_csv(path))
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return _normalize_record(_read_xlsx(path))

    raise ValueError(f"Unsupported file type: {suffix}")
