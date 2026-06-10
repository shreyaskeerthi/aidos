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

        if _is_blank(source_interface) and not _is_blank(source_module):
            source_port = _first_present(row_dict, ["port", "port_a", "source_port"])
            if not _is_blank(source_port):
                source_interface = f"{str(source_module).strip()}/{str(source_port).strip()}"

        if _is_blank(destination_interface) and not _is_blank(destination_module):
            destination_port = _first_present(row_dict, ["port_1", "port_b", "destination_port"])
            if not _is_blank(destination_port):
                destination_interface = f"{str(destination_module).strip()}/{str(destination_port).strip()}"

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


def parse_network_layout_workbook(path_str: str) -> dict[str, list[dict[str, Any]]]:
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

    vlan_seen: set[tuple[int, str]] = set()
    cable_seen: set[tuple[str, str, str, str]] = set()
    vlans: list[dict[str, Any]] = []
    cables: list[dict[str, Any]] = []

    def _accumulate_from_sheet(frame: pd.DataFrame) -> None:
        sheet_vlans, sheet_cables = _network_layout_from_frame(frame)
        for vlan in sheet_vlans:
            key = (int(vlan["vid"]), str(vlan.get("site") or ""))
            if key in vlan_seen:
                continue
            vlan_seen.add(key)
            vlans.append(vlan)

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
            cables.append(cable)

    def _scan_workbook_frames(book: dict[Any, pd.DataFrame]) -> None:
        preferred_tokens = {"network", "layout", "cable", "vlan", "l2", "fabric"}
        preferred_frames = [
            frame
            for sheet_name, frame in book.items()
            if any(token in str(sheet_name).strip().lower() for token in preferred_tokens)
        ]

        for frame in preferred_frames:
            _accumulate_from_sheet(frame)

        if not vlans and not cables:
            for frame in book.values():
                _accumulate_from_sheet(frame)

    _scan_workbook_frames(workbook)

    # Many customer workbooks use two-row headers. Retry with header=1 if needed.
    if not vlans and not cables:
        try:
            header1_workbook = pd.read_excel(path, sheet_name=None, header=1)
            _scan_workbook_frames(header1_workbook)
        except Exception:
            pass

    return {"vlans": vlans, "cables": cables}


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

    raise ValueError(
        "No BOM sheet with deployment intent fields found. "
        "Expected a BOM/Bill of Materials sheet containing gpu_model and related fields."
    )


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
