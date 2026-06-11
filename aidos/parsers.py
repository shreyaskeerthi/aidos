"""Input parsers for AIDOS intent and site reality files."""

from __future__ import annotations

import csv
import json
import re
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


def _canonical_col_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        is_na = pd.isna(value)
        # pandas may return array-like for non-scalar objects.
        if isinstance(is_na, (list, tuple)):
            return all(bool(item) for item in is_na)
        if hasattr(is_na, "all"):
            return bool(is_na.all())
        return bool(is_na)
    except Exception:
        return False


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if not _is_blank(value):
            return value
    return None


def _first_semantic(
    row: dict[str, Any],
    *,
    role_tokens: set[str],
    field_tokens: set[str],
    exclude_tokens: set[str] | None = None,
) -> Any:
    exclude = exclude_tokens or set()
    for key, value in row.items():
        if _is_blank(value):
            continue
        key_text = str(key).strip().lower()
        if not any(token in key_text for token in field_tokens):
            continue
        if not any(token in key_text for token in role_tokens):
            continue
        if any(token in key_text for token in exclude):
            continue
        return value
    return None


def _split_endpoint(value: Any) -> tuple[str | None, str | None]:
    if _is_blank(value):
        return None, None
    text = str(value).strip()
    if not text:
        return None, None

    # Common form: "device:interface"
    if ":" in text:
        left, right = text.split(":", 1)
        left = left.strip()
        right = right.strip()
        if left and right:
            return left, right

    # Common form: "device interface"
    parts = text.split()
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(parts[1:]).strip()

    return None, None


def _extract_link_from_text(value: Any) -> tuple[str | None, str | None, str | None, str | None]:
    if _is_blank(value):
        return None, None, None, None
    text = str(value).strip()
    if "<->" not in text:
        return None, None, None, None

    pattern = re.compile(
        r"(?P<src_dev>\S+)\s+RU\d+\s+(?P<src_if>[A-Za-z0-9_/.-]+)\s*<->\s*"
        r"(?P<dst_dev>\S+)\s+RU\d+\s+(?P<dst_if>[A-Za-z0-9_/.-]+)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None, None, None
    return (
        match.group("src_dev").strip(),
        match.group("src_if").strip(),
        match.group("dst_dev").strip(),
        match.group("dst_if").strip(),
    )


def _parse_vlan_id(value: Any) -> int | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"\d+", text)
    if match:
        return int(match.group(0))
    return None


def _normalize_face(value: Any) -> str:
    if _is_blank(value):
        return "front"
    text = str(value).strip().lower()
    if text.startswith("rear") or text == "r":
        return "rear"
    return "front"


def _parse_rack_position(value: Any) -> int | None:
    parsed = _parse_int(value)
    if parsed is None:
        return None
    if parsed < 1 or parsed > 60:
        return None
    return parsed


def _clean_rack_device_name(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return None

    lowered = text.lower()
    skip_tokens = {
        "blank",
        "spare",
        "empty",
        "cable passthrough",
        "cable management",
        "filler",
        "front view",
        "rear view",
        "ru",
    }
    if any(token in lowered for token in skip_tokens):
        return None
    return text


def _rack_name_from_sheet(sheet_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", sheet_name.strip())
    return cleaned if cleaned else "rack-elevation"


def _rack_elevation_from_frame(frame: pd.DataFrame, sheet_name: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    default_rack = _rack_name_from_sheet(sheet_name)

    # Structured-table style: explicit rack/device/U columns.
    col_map = {col: _canonical_col_name(str(col)) for col in frame.columns}
    normalized = frame.rename(columns=col_map)
    for _, row in normalized.iterrows():
        row_dict = row.to_dict()
        name = _clean_rack_device_name(
            _first_present(
                row_dict,
                ["device_name", "device", "hostname", "equipment", "asset", "name"],
            )
        )
        position = _parse_rack_position(
            _first_present(
                row_dict,
                ["ru", "rack_u", "rack_unit", "u", "position", "slot"],
            )
        )
        if name is None or position is None:
            continue

        rack = _first_present(row_dict, ["rack", "rack_name", "cabinet", "enclosure"])
        rack_name = str(rack).strip() if not _is_blank(rack) else default_rack
        face = _normalize_face(_first_present(row_dict, ["face", "side", "view"]))
        key = (name, rack_name, position)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "name": name,
                "rack": rack_name,
                "position": position,
                "face": face,
            }
        )

    # Grid style: one column with U numbers and adjacent columns with device labels.
    grid = frame.fillna("")
    row_count, col_count = grid.shape
    for col_idx in range(col_count):
        numbered_rows: list[tuple[int, int]] = []
        for row_idx in range(row_count):
            position = _parse_rack_position(grid.iat[row_idx, col_idx])
            if position is not None:
                numbered_rows.append((row_idx, position))

        # Require enough RU markers so random numeric columns are ignored.
        if len(numbered_rows) < 8:
            continue

        for neighbor in (col_idx - 1, col_idx + 1):
            if neighbor < 0 or neighbor >= col_count:
                continue
            for row_idx, position in numbered_rows:
                name = _clean_rack_device_name(grid.iat[row_idx, neighbor])
                if name is None:
                    continue

                key = (name, default_rack, position)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    {
                        "name": name,
                        "rack": default_rack,
                        "position": position,
                        "face": "front",
                    }
                )

    return entries


def _network_layout_from_frame(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if frame.empty:
        return [], []

    col_map = {col: _canonical_col_name(str(col)) for col in frame.columns}
    normalized = frame.rename(columns=col_map)

    vlan_entries: list[dict[str, Any]] = []
    cable_entries: list[dict[str, Any]] = []

    for _, row in normalized.iterrows():
        row_dict = row.to_dict()

        vlan_id = _parse_vlan_id(
            _first_present(row_dict, ["vlan_id", "vid", "vlan", "vlanid"])
        )
        if vlan_id is not None:
            vlan_name = _first_present(row_dict, ["vlan_name", "name", "segment", "network"])
            site = _first_present(row_dict, ["site", "site_slug", "location"])
            prefix = _first_present(row_dict, ["prefix", "subnet", "cidr"])
            vrf = _first_present(row_dict, ["vrf", "vrf_name"])
            vlan_entries.append(
                {
                    "vid": vlan_id,
                    "name": str(vlan_name).strip() if not _is_blank(vlan_name) else f"vlan-{vlan_id}",
                    "site": str(site).strip() if not _is_blank(site) else None,
                    "prefix": str(prefix).strip() if not _is_blank(prefix) else None,
                    "vrf": str(vrf).strip() if not _is_blank(vrf) else None,
                }
            )

        source_device = _first_present(
            row_dict,
            [
                "source_device",
                "from_device",
                "a_device",
                "device_a",
                "device_1",
                "device_name",
                "rack",
            ],
        )
        source_interface = _first_present(
            row_dict,
            [
                "source_interface",
                "from_interface",
                "a_interface",
                "interface_a",
                "source_port",
                "port_a",
                "port",
            ],
        )
        destination_device = _first_present(
            row_dict,
            [
                "destination_device",
                "dest_device",
                "to_device",
                "b_device",
                "device_b",
                "device_2",
                "device_name_1",
                "rack_1",
            ],
        )
        destination_interface = _first_present(
            row_dict,
            [
                "destination_interface",
                "dest_interface",
                "to_interface",
                "b_interface",
                "interface_b",
                "destination_port",
                "port_b",
                "port_1",
            ],
        )

        source_module = _first_present(row_dict, ["module", "module_", "module_number", "module_no"])
        destination_module = _first_present(
            row_dict, ["module_1", "module_1_", "module_number_1", "module_no_1"]
        )

        if not _is_blank(source_module):
            if _is_blank(source_interface):
                source_port = _first_present(row_dict, ["port", "port_a", "source_port"])
                if not _is_blank(source_port):
                    source_interface = f"{str(source_module).strip()}/{str(source_port).strip()}"
            else:
                source_interface_text = str(source_interface).strip()
                if "/" not in source_interface_text:
                    source_interface = f"{str(source_module).strip()}/{source_interface_text}"

        if not _is_blank(destination_module):
            if _is_blank(destination_interface):
                destination_port = _first_present(row_dict, ["port_1", "port_b", "destination_port"])
                if not _is_blank(destination_port):
                    destination_interface = (
                        f"{str(destination_module).strip()}/{str(destination_port).strip()}"
                    )
            else:
                destination_interface_text = str(destination_interface).strip()
                if "/" not in destination_interface_text:
                    destination_interface = (
                        f"{str(destination_module).strip()}/{destination_interface_text}"
                    )

        # Semantic fallback for non-standard headers (for example, A-side/B-side node/port).
        if _is_blank(source_device):
            source_device = _first_semantic(
                row_dict,
                role_tokens={"source", "src", "from", "a_side", "aside", "a_end", "device_a", "left", "origin", "start"},
                field_tokens={"device", "host", "node", "switch", "server", "router"},
                exclude_tokens={"destination", "dest", "to", "b_side", "b_end", "device_b", "right", "target", "end"},
            )
        if _is_blank(destination_device):
            destination_device = _first_semantic(
                row_dict,
                role_tokens={"destination", "dest", "to", "b_side", "bside", "b_end", "device_b", "right", "target", "end"},
                field_tokens={"device", "host", "node", "switch", "server", "router"},
                exclude_tokens={"source", "src", "from", "a_side", "a_end", "device_a", "left", "origin", "start"},
            )
        if _is_blank(source_interface):
            source_interface = _first_semantic(
                row_dict,
                role_tokens={"source", "src", "from", "a_side", "aside", "a_end", "interface_a", "port_a", "left", "origin", "start"},
                field_tokens={"interface", "port", "intf", "nic", "adapter", "ethernet", "eth"},
                exclude_tokens={"destination", "dest", "to", "b_side", "b_end", "interface_b", "port_b", "right", "target", "end"},
            )
        if _is_blank(destination_interface):
            destination_interface = _first_semantic(
                row_dict,
                role_tokens={"destination", "dest", "to", "b_side", "bside", "b_end", "interface_b", "port_b", "right", "target", "end"},
                field_tokens={"interface", "port", "intf", "nic", "adapter", "ethernet", "eth"},
                exclude_tokens={"source", "src", "from", "a_side", "a_end", "interface_a", "port_a", "left", "origin", "start"},
            )

        # Endpoint-string fallback such as "from endpoint" -> "leaf-01:Eth1/1".
        if any(_is_blank(value) for value in [source_device, source_interface]):
            from_endpoint = _first_present(
                row_dict,
                ["from", "from_endpoint", "source_endpoint", "a_endpoint", "endpoint_a"],
            )
            parsed_device, parsed_interface = _split_endpoint(from_endpoint)
            if _is_blank(source_device) and parsed_device is not None:
                source_device = parsed_device
            if _is_blank(source_interface) and parsed_interface is not None:
                source_interface = parsed_interface

        if any(_is_blank(value) for value in [destination_device, destination_interface]):
            to_endpoint = _first_present(
                row_dict,
                ["to", "to_endpoint", "destination_endpoint", "b_endpoint", "endpoint_b"],
            )
            parsed_device, parsed_interface = _split_endpoint(to_endpoint)
            if _is_blank(destination_device) and parsed_device is not None:
                destination_device = parsed_device
            if _is_blank(destination_interface) and parsed_interface is not None:
                destination_interface = parsed_interface

        if any(
            _is_blank(value)
            for value in [source_device, source_interface, destination_device, destination_interface]
        ):
            for candidate_value in row_dict.values():
                src_dev, src_if, dst_dev, dst_if = _extract_link_from_text(candidate_value)
                if src_dev is None:
                    continue
                if _is_blank(source_device):
                    source_device = src_dev
                if _is_blank(source_interface):
                    source_interface = src_if
                if _is_blank(destination_device):
                    destination_device = dst_dev
                if _is_blank(destination_interface):
                    destination_interface = dst_if
                break

        if not any(
            _is_blank(value)
            for value in [
                source_device,
                source_interface,
                destination_device,
                destination_interface,
            ]
        ):
            cable_entries.append(
                {
                    "source_device": str(source_device).strip(),
                    "source_interface": str(source_interface).strip(),
                    "destination_device": str(destination_device).strip(),
                    "destination_interface": str(destination_interface).strip(),
                    "type": str(_first_present(row_dict, ["cable_type", "media", "type"]) or "cat6").strip(),
                    "status": str(_first_present(row_dict, ["status", "link_status"]) or "connected").strip(),
                    "label": str(
                        _first_present(row_dict, ["label", "cable_id", "cable_label"])
                        or (
                            f"{str(source_device).strip()}:{str(source_interface).strip()}"
                            f"<->{str(destination_device).strip()}:{str(destination_interface).strip()}"
                        )
                    ).strip(),
                }
            )

    return vlan_entries, cable_entries


def parse_network_layout_workbook(path_str: str) -> dict[str, Any]:
    """Extract VLAN and cable rows from workbook sheets.

    The parser is intentionally permissive with sheet names and header aliases so
    real-world design workbooks can be ingested without strict templates.
    """

    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("Network layout workbook must be an Excel file (.xlsx/.xlsm/.xls)")

    workbook = pd.read_excel(path, sheet_name=None)

    def _scan_workbook_frames(book: dict[Any, pd.DataFrame]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        vlan_seen: set[tuple[int, str]] = set()
        cable_seen: set[tuple[str, str, str, str]] = set()
        found_vlans: list[dict[str, Any]] = []
        found_cables: list[dict[str, Any]] = []

        def _accumulate_from_sheet(frame: pd.DataFrame) -> None:
            sheet_vlans, sheet_cables = _network_layout_from_frame(frame)
            for vlan in sheet_vlans:
                key = (int(vlan["vid"]), str(vlan.get("site") or ""))
                if key in vlan_seen:
                    continue
                vlan_seen.add(key)
                found_vlans.append(vlan)

            for cable in sheet_cables:
                key = (
                    cable["source_device"],
                    cable["source_interface"],
                    cable["destination_device"],
                    cable["destination_interface"],
                )
                reverse_key = (
                    cable["destination_device"],
                    cable["destination_interface"],
                    cable["source_device"],
                    cable["source_interface"],
                )
                if key in cable_seen or reverse_key in cable_seen:
                    continue
                cable_seen.add(key)
                found_cables.append(cable)

        preferred_tokens = {"network", "layout", "cable", "vlan", "l2", "fabric"}
        preferred_frames = [
            frame
            for sheet_name, frame in book.items()
            if any(token in str(sheet_name).strip().lower() for token in preferred_tokens)
        ]

        for frame in preferred_frames:
            _accumulate_from_sheet(frame)

        if not found_vlans and not found_cables:
            for frame in book.values():
                _accumulate_from_sheet(frame)

        return found_vlans, found_cables

    def _scan_rack_elevation_frames(book: dict[Any, pd.DataFrame]) -> list[dict[str, Any]]:
        rack_entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for sheet_name, frame in book.items():
            sheet_name_text = str(sheet_name).strip().lower()
            if "rack" not in sheet_name_text or "elevation" not in sheet_name_text:
                continue
            for entry in _rack_elevation_from_frame(frame, str(sheet_name)):
                key = (
                    str(entry.get("name", "")).strip(),
                    str(entry.get("rack", "")).strip(),
                    int(entry.get("position", 0)),
                )
                if key in seen:
                    continue
                seen.add(key)
                rack_entries.append(entry)
        return rack_entries

    vlans, cables = _scan_workbook_frames(workbook)
    rack_devices = _scan_rack_elevation_frames(workbook)

    # Many customer workbooks use two-row headers. Parse header=1 and choose richer cable extraction.
    try:
        header1_workbook = pd.read_excel(path, sheet_name=None, header=1)
        vlans_h1, cables_h1 = _scan_workbook_frames(header1_workbook)

        endpoints_h0 = {
            str(item.get("source_device", "")) for item in cables
        } | {
            str(item.get("destination_device", "")) for item in cables
        }
        endpoints_h1 = {
            str(item.get("source_device", "")) for item in cables_h1
        } | {
            str(item.get("destination_device", "")) for item in cables_h1
        }

        # Prefer header=1 parsing when it yields more distinct endpoints.
        rack_devices_h1 = _scan_rack_elevation_frames(header1_workbook)

        if len(endpoints_h1) > len(endpoints_h0):
            cables = cables_h1
            if len(vlans_h1) >= len(vlans):
                vlans = vlans_h1
        elif (not cables) and cables_h1:
            cables = cables_h1
            if vlans_h1:
                vlans = vlans_h1
        elif (not vlans) and vlans_h1:
            vlans = vlans_h1

        if len(rack_devices_h1) > len(rack_devices):
            rack_devices = rack_devices_h1
    except Exception:
        pass

    return {"vlans": vlans, "cables": cables, "rack_devices": rack_devices}


def _sheet_to_key_value(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}

    cols = [str(col).strip().lower() for col in frame.columns]
    if {"field", "value"}.issubset(set(cols)):
        key_col = frame.columns[cols.index("field")]
        value_col = frame.columns[cols.index("value")]
        parsed = {
            str(row[key_col]).strip(): row[value_col]
            for _, row in frame.iterrows()
            if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
        }
        return parsed

    if len(frame.columns) >= 2:
        key_col = frame.columns[0]
        value_col = frame.columns[1]
        parsed = {
            str(row[key_col]).strip(): row[value_col]
            for _, row in frame.iterrows()
            if str(row[key_col]).strip() and str(row[key_col]).strip().lower() != "nan"
        }
        return parsed

    return {}


def _sheet_to_row_record(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}

    col_map = {col: _canonical_col_name(str(col)) for col in frame.columns}
    normalized = frame.rename(columns=col_map)
    for _, row in normalized.iterrows():
        row_dict = {
            str(k): v
            for k, v in row.to_dict().items()
            if not _is_blank(v)
        }
        if row_dict:
            return row_dict
    return {}


def parse_deployment_intent_workbook(path_str: str) -> dict[str, Any]:
    """Extract deployment intent from BOM-like workbook sheets."""

    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("Deployment intent workbook must be an Excel file (.xlsx/.xlsm/.xls)")

    workbook = pd.read_excel(path, sheet_name=None)
    name_tokens = {"bom", "bill", "materials", "intent", "deployment"}

    def _parse_intent_frame(frame: pd.DataFrame) -> dict[str, Any] | None:
        candidate = _sheet_to_key_value(frame)
        if not candidate:
            candidate = _sheet_to_row_record(frame)
        if not candidate:
            return None

        normalized = _normalize_record(candidate)
        if "gpu_model" not in normalized:
            return None

        model = DeploymentIntent.model_validate(normalized)
        return model.model_dump(mode="python")

    preferred_frames = [
        frame
        for sheet_name, frame in workbook.items()
        if any(token in str(sheet_name).strip().lower() for token in name_tokens)
    ]

    for frame in preferred_frames:
        parsed = _parse_intent_frame(frame)
        if parsed is not None:
            return parsed

    # Fallback for workbooks that hide BOM on non-standard sheet names.
    for frame in workbook.values():
        parsed = _parse_intent_frame(frame)
        if parsed is not None:
            return parsed

    metadata = parse_workbook_metadata(path_str)
    if bool(metadata.get("bom_present")):
        deployment_name = str(metadata.get("project_name") or "aidos-adaptive-deployment")
        gpu_model = str(metadata.get("gpu_model_hint") or "UNSPECIFIED")
        node_count_hint = metadata.get("node_count_hint")
        try:
            node_count = max(int(node_count_hint), 1) if node_count_hint is not None else 1
        except Exception:
            node_count = 1
        model = DeploymentIntent(
            deployment_name=deployment_name,
            gpu_model=gpu_model,
            node_count=node_count,
            target_platform=None,
            required_vlans=[],
        )
        return model.model_dump(mode="python")

    raise ValueError(
        "No BOM sheet with deployment intent fields found. "
        "Expected a BOM/Bill of Materials sheet containing gpu_model and related fields."
    )


def parse_workbook_metadata(path_str: str) -> dict[str, Any]:
    """Extract project/context hints from mixed intake workbooks."""

    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("Workbook metadata parser requires an Excel file")

    workbook = pd.read_excel(path, sheet_name=None, header=None)
    sheet_names = [str(name).strip() for name in workbook.keys()]
    lower_names = [name.lower() for name in sheet_names]

    bom_present = any("bom" in name or "bill" in name for name in lower_names)
    rack_count = sum(
        1
        for name in lower_names
        if (name.startswith("rack-") or name.startswith("rack "))
        and "elevation" not in name
        and "layout" not in name
    )

    text_blob_parts: list[str] = []
    for frame in workbook.values():
        if frame.empty:
            continue
        sample = frame.head(25).fillna("")
        for row in sample.itertuples(index=False):
            joined = " ".join(str(cell).strip() for cell in row if str(cell).strip())
            if joined:
                text_blob_parts.append(joined)
    text_blob = "\n".join(text_blob_parts)
    text_blob_l = text_blob.lower()

    customer_name: str | None = None
    project_name: str | None = None
    site_name: str | None = None

    # Common title form: "Meridian Networks - Phoenix DC Build Phase 1 ..."
    title_match = re.search(r"([A-Za-z0-9& ._-]+)\s+-\s+([A-Za-z0-9& ._-]+)", text_blob)
    if title_match:
        customer_name = title_match.group(1).strip()
        project_name = title_match.group(2).strip()

    site_match = re.search(r"\b([A-Za-z]+\s+DC)\b", text_blob, flags=re.IGNORECASE)
    if site_match:
        site_name = site_match.group(1).strip()

    gpu_model_hint: str | None = None
    for token in ["GB200", "B200", "H200", "H100"]:
        if re.search(rf"\b{token}\b", text_blob_l, flags=re.IGNORECASE):
            gpu_model_hint = token
            break

    metadata: dict[str, Any] = {
        "sheet_names": sheet_names,
        "bom_present": bom_present,
        "rack_count": rack_count,
        "node_count_hint": rack_count if rack_count > 0 else None,
        "customer_name": customer_name,
        "project_name": project_name,
        "site_name": site_name,
        "gpu_model_hint": gpu_model_hint,
    }
    return {k: v for k, v in metadata.items() if v is not None}


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
    best_raw: dict[str, Any] = {}
    best_score = -1

    score_markers = {
        "loading_dock",
        "server_lift",
        "rack_floor_psf",
        "available_power_kw",
        "available_cooling_kw",
        "vlan_ids",
        "gpu_model",
        "node_count",
        "deployment_name",
        "customer_name",
        "project_name",
        "site_name",
        "workload_name",
        "gpu_model_preference",
        "desired_node_count",
    }

    for frame in workbook.values():
        if frame.empty:
            continue

        candidate = _sheet_to_key_value(frame)
        if not candidate:
            continue

        normalized = _normalize_record(candidate)
        score = len(score_markers.intersection(set(normalized.keys())))
        if score > best_score:
            best_score = score
            best_raw = candidate

    return best_raw


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
