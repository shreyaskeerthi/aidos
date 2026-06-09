"""Input parsers for AIDOS intent and site reality files."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from aidos.schemas import DeploymentIntent, SiteSurvey


_KEY_MAP = {
    "loading dock": "loading_dock",
    "server lift": "server_lift",
    "rack floor psf": "rack_floor_psf",
    "rack psf": "rack_floor_psf",
    "liquid cooling": "liquid_cooling",
    "power": "power_profile",
    "power profile": "power_profile",
    "available circuits": "available_circuits",
    "uplinks": "uplinks",
    "40g ports": "ports_40g",
    "ports 40g": "ports_40g",
    "vlan config needed": "vlan_config_needed",
    "vlan ids": "vlan_ids",
    "required vlans": "required_vlans",
    "network diagram provided": "network_diagram_provided",
    "layout blueprint provided": "layout_blueprint_provided",
    "available rack slots": "available_rack_slots",
    "available power kw": "available_power_kw",
    "available cooling kw": "available_cooling_kw",
    "deployment name": "deployment_name",
    "gpu model": "gpu_model",
    "node count": "node_count",
    "target platform": "target_platform",
}

_BOOL_KEYS = {
    "loading_dock",
    "server_lift",
    "liquid_cooling",
    "available_circuits",
    "ports_40g",
    "vlan_config_needed",
    "network_diagram_provided",
    "layout_blueprint_provided",
}
_INT_KEYS = {"node_count", "available_rack_slots"}
_FLOAT_KEYS = {"rack_floor_psf", "available_power_kw", "available_cooling_kw"}
_LIST_KEYS = {"vlan_ids", "required_vlans"}


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


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in record.items():
        key = str(raw_key).strip().lower().replace("_", " ")
        canonical = _KEY_MAP.get(key, key.replace(" ", "_"))
        normalized[canonical] = raw_value

    for key in _BOOL_KEYS:
        if key in normalized:
            parsed = _parse_bool(normalized[key])
            if parsed is not None:
                normalized[key] = parsed

    for key in _INT_KEYS:
        if key in normalized:
            parsed = _parse_int(normalized[key])
            if parsed is not None:
                normalized[key] = parsed

    for key in _FLOAT_KEYS:
        if key in normalized:
            parsed = _parse_float(normalized[key])
            if parsed is not None:
                normalized[key] = parsed

    for key in _LIST_KEYS:
        if key in normalized:
            normalized[key] = _parse_list(normalized[key])

    return normalized


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON payload must be an object.")
    return data


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("YAML payload must be a mapping.")
    return data


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
    workbook = pd.read_excel(path, sheet_name=None)
    for frame in workbook.values():
        if frame.empty:
            continue

        cols = [str(col).strip().lower() for col in frame.columns]
        if {"field", "value"}.issubset(set(cols)):
            key_col = frame.columns[cols.index("field")]
            value_col = frame.columns[cols.index("value")]
            parsed = {
                str(row[key_col]).strip(): row[value_col]
                for _, row in frame.iterrows()
                if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
            }
            if parsed:
                return parsed

        if len(frame.columns) >= 2:
            key_col = frame.columns[0]
            value_col = frame.columns[1]
            parsed = {
                str(row[key_col]).strip(): row[value_col]
                for _, row in frame.iterrows()
                if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
            }
            if parsed:
                return parsed

    return {}


def read_key_value_file(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = _read_json(path)
    elif suffix in {".yaml", ".yml"}:
        raw = _read_yaml(path)
    elif suffix == ".csv":
        raw = _read_csv(path)
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        raw = _read_xlsx(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    return _normalize_record(raw)


def parse_site_survey(path_str: str) -> tuple[SiteSurvey, dict[str, Any]]:
    normalized = read_key_value_file(path_str)
    return SiteSurvey.model_validate(normalized), normalized


def parse_bom(path_str: str) -> tuple[DeploymentIntent, dict[str, Any]]:
    normalized = read_key_value_file(path_str)
    return DeploymentIntent.model_validate(normalized), normalized
