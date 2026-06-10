from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from aidos.ingestion import ingest_inputs
from aidos.netbox_sync import build_netbox_payload
from aidos.parsers import parse_deployment_intent_workbook, parse_network_layout_workbook
from aidos.truth import build_canonical_sot


def test_parse_network_layout_workbook_extracts_vlans_and_cables(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "network_layout.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    frame = pd.DataFrame(
        [
            {
                "VLAN ID": 3101,
                "VLAN Name": "compute",
                "Site": "sjc-pop-2",
                "Prefix": "10.31.1.0/24",
                "VRF": "sjc-vrf",
            },
            {
                "Source Device": "leaf-01",
                "Source Interface": "Eth1/1",
                "Destination Device": "spine-01",
                "Destination Interface": "Eth1/49",
                "Cable Type": "smf",
            },
        ]
    )

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {"Network Layout": frame},
    )

    parsed = parse_network_layout_workbook(str(workbook_path))

    assert parsed["vlans"] == [
        {
            "vid": 3101,
            "name": "compute",
            "site": "sjc-pop-2",
            "prefix": "10.31.1.0/24",
            "vrf": "sjc-vrf",
        }
    ]
    assert parsed["cables"] == [
        {
            "source_device": "leaf-01",
            "source_interface": "Eth1/1",
            "destination_device": "spine-01",
            "destination_interface": "Eth1/49",
            "type": "smf",
            "status": "connected",
            "label": "leaf-01:Eth1/1<->spine-01:Eth1/49",
        }
    ]


def test_build_netbox_payload_merges_network_layout(tmp_path: Path, monkeypatch) -> None:
    survey_path = tmp_path / "survey.json"
    bom_path = tmp_path / "bom.json"
    context_path = tmp_path / "context.json"
    workbook_path = tmp_path / "layout.xlsx"

    survey_path.write_text(
        json.dumps(
            {
                "loading_dock": "yes",
                "server_lift": "yes",
                "rack_floor_psf": 200,
                "available_circuits": "yes",
                "available_rack_slots": 16,
                "available_power_kw": 120,
                "available_cooling_kw": 120,
                "vlan_ids": ["3101"],
            }
        ),
        encoding="utf-8",
    )
    bom_path.write_text(
        json.dumps(
            {
                "deployment_name": "sjc-phase2",
                "gpu_model": "H100",
                "node_count": 4,
                "target_platform": "Cisco AI Pod",
            }
        ),
        encoding="utf-8",
    )
    context_path.write_text(
        json.dumps(
            {
                "project_name": "sjc-phase2",
                "site_name": "sjc-pop-2",
            }
        ),
        encoding="utf-8",
    )
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Network Layout": pd.DataFrame(
                [
                    {
                        "VLAN ID": 3102,
                        "VLAN Name": "storage",
                        "Site": "sjc-pop-2",
                    },
                    {
                        "Source Device": "sjc-phase2-node-1",
                        "Source Interface": "eth0",
                        "Destination Device": "leaf-01",
                        "Destination Interface": "Ethernet1/11",
                    },
                ]
            )
        },
    )

    bundle = ingest_inputs(
        str(survey_path),
        bom_path=str(bom_path),
        context_path=str(context_path),
        network_layout_path=str(workbook_path),
    )
    sot = build_canonical_sot(bundle)
    payload = build_netbox_payload(sot, network_layout=bundle.network_layout)

    vids = {str(vlan["vid"]) for vlan in payload.vlans}
    assert "3101" in vids
    assert "3102" in vids
    assert len(payload.cables) == 1
    assert payload.cables[0]["source_device"] == "sjc-phase2-node-1"
    assert payload.cables[0]["destination_device"] == "leaf-01"


def test_parse_deployment_intent_workbook_reads_bom_sheet_not_first(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "mixed_intake.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    survey_frame = pd.DataFrame(
        [
            {"Field": "loading_dock", "Value": "yes"},
            {"Field": "server_lift", "Value": "yes"},
        ]
    )
    bom_frame = pd.DataFrame(
        [
            {"Field": "deployment_name", "Value": "from-bom-sheet"},
            {"Field": "gpu_model", "Value": "H100"},
            {"Field": "node_count", "Value": 8},
            {"Field": "target_platform", "Value": "Cisco AI Pod"},
            {"Field": "required_vlans", "Value": "101,102,103"},
        ]
    )

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Site Survey": survey_frame,
            "Bill of Materials": bom_frame,
        },
    )

    parsed = parse_deployment_intent_workbook(str(workbook_path))

    assert parsed["deployment_name"] == "from-bom-sheet"
    assert parsed["gpu_model"] == "H100"
    assert parsed["node_count"] == 8
    assert parsed["required_vlans"] == ["101", "102", "103"]


def test_ingest_inputs_uses_bom_sheet_from_excel_path(tmp_path: Path, monkeypatch) -> None:
    survey_path = tmp_path / "survey.json"
    workbook_path = tmp_path / "intake.xlsx"

    survey_path.write_text(
        json.dumps(
            {
                "loading_dock": "yes",
                "server_lift": "yes",
                "rack_floor_psf": 200,
            }
        ),
        encoding="utf-8",
    )
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Summary": pd.DataFrame([{"Field": "note", "Value": "metadata"}]),
            "BOM": pd.DataFrame(
                [
                    {"Field": "deployment_name", "Value": "bom-intake"},
                    {"Field": "gpu_model", "Value": "B200"},
                    {"Field": "node_count", "Value": 2},
                ]
            ),
        },
    )

    bundle = ingest_inputs(str(survey_path), bom_path=str(workbook_path))

    assert bundle.intent.deployment_name == "bom-intake"
    assert bundle.intent.gpu_model == "B200"
    assert bundle.intent.node_count == 2


def test_parse_network_layout_workbook_falls_back_when_sheet_name_nonstandard(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "fakedata.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Topology Matrix": pd.DataFrame(
                [
                    {
                        "VLAN ID": 3103,
                        "VLAN Name": "ops",
                    },
                    {
                        "Source Device": "leaf-01",
                        "Source Interface": "Eth1/11",
                        "Destination Device": "spine-01",
                        "Destination Interface": "Eth1/49",
                    },
                ]
            )
        },
    )

    parsed = parse_network_layout_workbook(str(workbook_path))

    assert len(parsed["vlans"]) == 1
    assert parsed["vlans"][0]["vid"] == 3103
    assert len(parsed["cables"]) == 1
    assert parsed["cables"][0]["source_device"] == "leaf-01"


def test_parse_deployment_intent_workbook_falls_back_when_sheet_name_nonstandard(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "fakedata.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Sheet Alpha": pd.DataFrame([{"Field": "note", "Value": "ignore"}]),
            "Planning Inputs": pd.DataFrame(
                [
                    {"Field": "deployment_name", "Value": "adaptive-bom"},
                    {"Field": "gpu_model", "Value": "H100"},
                    {"Field": "node_count", "Value": 6},
                ]
            ),
        },
    )

    parsed = parse_deployment_intent_workbook(str(workbook_path))
    assert parsed["deployment_name"] == "adaptive-bom"
    assert parsed["gpu_model"] == "H100"
    assert parsed["node_count"] == 6


def test_parse_network_layout_workbook_extracts_cables_from_a_b_side_headers(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "fakedata.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Sheet1": pd.DataFrame(
                [
                    {
                        "A-side node": "leaf-01",
                        "A-side port": "Eth1/1",
                        "B-side node": "spine-01",
                        "B-side port": "Eth1/49",
                    }
                ]
            )
        },
    )

    parsed = parse_network_layout_workbook(str(workbook_path))

    assert len(parsed["cables"]) == 1
    assert parsed["cables"][0]["source_device"] == "leaf-01"
    assert parsed["cables"][0]["source_interface"] == "Eth1/1"
    assert parsed["cables"][0]["destination_device"] == "spine-01"
    assert parsed["cables"][0]["destination_interface"] == "Eth1/49"


def test_parse_network_layout_workbook_extracts_cables_from_endpoint_strings(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "fakedata.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {
            "Sheet1": pd.DataFrame(
                [
                    {
                        "From Endpoint": "leaf-02:Eth1/2",
                        "To Endpoint": "spine-02:Eth1/50",
                    }
                ]
            )
        },
    )

    parsed = parse_network_layout_workbook(str(workbook_path))

    assert len(parsed["cables"]) == 1
    assert parsed["cables"][0]["source_device"] == "leaf-02"
    assert parsed["cables"][0]["source_interface"] == "Eth1/2"
    assert parsed["cables"][0]["destination_device"] == "spine-02"
    assert parsed["cables"][0]["destination_interface"] == "Eth1/50"


def test_parse_network_layout_workbook_two_row_header_style_extracts_cables(
    tmp_path: Path, monkeypatch
) -> None:
    workbook_path = tmp_path / "fakedata.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")

    # Mirrors the real workbook style where source/destination columns appear as
    # *Device Name, Module #, *Port and duplicated destination columns with .1 suffix.
    frame = pd.DataFrame(
        [
            {
                "Make/Model": "N9K-C9508",
                "Rack": "R0501-SP-A",
                "*RU": 5,
                "*Device Name": "Spine Switch A",
                "Module #": "m1",
                "*Port": 9,
                "<------>": "R0501-SP-A RU5 m1/9 <-> R0503-LF-A RU5 m1/9",
                "Make/Model.1": "N9K-C9508",
                "Rack.1": "R0503-LF-A",
                "*RU.1": 5,
                "*Device Name.1": "Leaf Switch A",
                "Module #.1": "m1",
                "*Port.1": 9,
                "Cable Type": "QSFP-DD AOC",
                "Length": "10M",
            }
        ]
    )

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *_args, **_kwargs: {"Network Layout ": frame},
    )

    parsed = parse_network_layout_workbook(str(workbook_path))

    assert len(parsed["cables"]) == 1
    assert parsed["cables"][0]["source_device"] == "Spine Switch A"
    assert parsed["cables"][0]["source_interface"] == "m1/9"
    assert parsed["cables"][0]["destination_device"] == "Leaf Switch A"
    assert parsed["cables"][0]["destination_interface"] == "m1/9"


def test_build_netbox_payload_adds_devices_from_cable_endpoints() -> None:
    from aidos.schemas import CanonicalSoT, DeploymentIntent, ExpectedTruth, ProjectContext, SiteSurvey
    from aidos.netbox_sync import build_netbox_payload

    site = SiteSurvey()
    intent = DeploymentIntent(deployment_name="demo", gpu_model="H100", node_count=4)
    expected = ExpectedTruth.from_inputs(site, intent)
    sot = CanonicalSoT(
        project=ProjectContext(project_name="demo", site_name="demo-site"),
        intent=intent,
        site=site,
        expected=expected,
    )

    payload = build_netbox_payload(
        sot,
        network_layout={
            "vlans": [],
            "cables": [
                {
                    "source_device": "Spine Switch A",
                    "source_interface": "m1/1",
                    "destination_device": "Leaf Switch A",
                    "destination_interface": "m1/1",
                }
            ],
        },
    )

    device_names = {item["name"] for item in payload.devices}
    assert "demo-node-1" in device_names
    assert "Spine Switch A" in device_names
    assert "Leaf Switch A" in device_names
    assert len(payload.devices) >= 6
