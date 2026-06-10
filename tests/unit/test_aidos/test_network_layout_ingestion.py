from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from aidos.ingestion import ingest_inputs
from aidos.netbox_sync import build_netbox_payload
from aidos.parsers import parse_network_layout_workbook
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
