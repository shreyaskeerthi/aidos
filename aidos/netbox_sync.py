"""NetBox mapping, reconciliation, and sync client for AIDOS."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from aidos.schemas import CanonicalSoT, NetBoxPayload


class NetBoxClient:
    """NetBox REST/GraphQL client with reconciliation-aware upsert behavior."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 15.0,
        verify: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify = verify
        self.dry_run = dry_run or not bool(token)

    @classmethod
    def from_env(cls) -> "NetBoxClient":
        base_url = os.getenv("NETBOX_URL", "http://netbox.local")
        token = os.getenv("NETBOX_TOKEN")
        verify = os.getenv("NETBOX_VERIFY_TLS", "true").lower() in {"1", "true", "yes", "on"}
        dry_run = os.getenv("NETBOX_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
        return cls(base_url=base_url, token=token, verify=verify, dry_run=dry_run)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout, verify=self.verify, headers=self._headers()) as client:
            response = client.request(method, url, params=params, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = response.text.strip()
                raise ValueError(
                    f"NetBox API error {response.status_code} for {method} {path}: {body}"
                ) from exc
            if not response.text:
                return {}
            data = response.json()
            return data if isinstance(data, dict) else {"results": data}

    def query_graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute NetBox GraphQL query for intent/read-only retrieval."""
        if self.dry_run:
            return {"status": "dry_run", "query": query, "variables": variables or {}}
        return self._request(
            "POST",
            "/graphql/",
            payload={"query": query, "variables": variables or {}},
        )

    def _find_existing(self, endpoint: str, lookup_field: str, value: Any) -> dict[str, Any] | None:
        if self.dry_run:
            return None
        data = self._request("GET", endpoint, params={lookup_field: value, "limit": 1})
        results = data.get("results", [])
        if isinstance(results, list) and results:
            found = results[0]
            return found if isinstance(found, dict) else None
        return None

    @staticmethod
    def _reconcile(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
        diff: dict[str, Any] = {}
        for key, desired_value in desired.items():
            if desired_value is None:
                continue
            existing_value = existing.get(key)
            if existing_value != desired_value:
                diff[key] = {"from": existing_value, "to": desired_value}
        return diff

    def _upsert(self, endpoint: str, lookup_field: str, desired: dict[str, Any]) -> dict[str, Any]:
        desired = self._prepare_desired(endpoint, desired)
        lookup_value = desired.get(lookup_field)
        existing = self._find_existing(endpoint, lookup_field, lookup_value)

        if existing is None:
            if self.dry_run:
                return {"action": "create", "dry_run": True, "lookup": {lookup_field: lookup_value}}
            created = self._request("POST", endpoint, payload=desired)
            return {"action": "create", "id": created.get("id"), "lookup": {lookup_field: lookup_value}}

        diff = self._reconcile(existing, desired)
        if not diff:
            return {
                "action": "noop",
                "id": existing.get("id"),
                "lookup": {lookup_field: lookup_value},
            }

        if self.dry_run:
            return {
                "action": "update",
                "dry_run": True,
                "id": existing.get("id"),
                "lookup": {lookup_field: lookup_value},
                "diff": diff,
            }

        object_id = existing.get("id")
        patched = self._request("PATCH", f"{endpoint}{object_id}/", payload=desired)
        return {
            "action": "update",
            "id": patched.get("id", object_id),
            "lookup": {lookup_field: lookup_value},
            "diff": diff,
        }

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return normalized or "aidos"

    def _find_id(self, endpoint: str, lookup_field: str, value: Any) -> int | None:
        data = self._request("GET", endpoint, params={lookup_field: value, "limit": 1})
        results = data.get("results", [])
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                object_id = first.get("id")
                if isinstance(object_id, int):
                    return object_id
        return None

    def _ensure_region(self, region_name: str) -> int | None:
        region_id = self._find_id("/api/dcim/regions/", "name", region_name)
        if region_id is not None:
            return region_id
        created = self._request(
            "POST",
            "/api/dcim/regions/",
            payload={"name": region_name, "slug": self._slugify(region_name)},
        )
        object_id = created.get("id")
        return object_id if isinstance(object_id, int) else None

    def _ensure_device_role(self, role_name: str) -> int | None:
        role_id = self._find_id("/api/dcim/device-roles/", "name", role_name)
        if role_id is not None:
            return role_id
        created = self._request(
            "POST",
            "/api/dcim/device-roles/",
            payload={
                "name": role_name,
                "slug": self._slugify(role_name),
                "color": "9e9e9e",
            },
        )
        object_id = created.get("id")
        return object_id if isinstance(object_id, int) else None

    def _ensure_manufacturer(self, name: str = "AIDOS") -> int | None:
        manufacturer_id = self._find_id("/api/dcim/manufacturers/", "name", name)
        if manufacturer_id is not None:
            return manufacturer_id
        created = self._request(
            "POST",
            "/api/dcim/manufacturers/",
            payload={"name": name, "slug": self._slugify(name)},
        )
        object_id = created.get("id")
        return object_id if isinstance(object_id, int) else None

    def _ensure_device_type(self, model: str) -> int | None:
        manufacturer_id = self._ensure_manufacturer("AIDOS")
        if manufacturer_id is None:
            return None
        device_type_id = self._find_id("/api/dcim/device-types/", "model", model)
        if device_type_id is not None:
            return device_type_id
        created = self._request(
            "POST",
            "/api/dcim/device-types/",
            payload={
                "manufacturer": manufacturer_id,
                "model": model,
                "slug": self._slugify(model),
                "u_height": 2,
                "is_full_depth": True,
            },
        )
        object_id = created.get("id")
        return object_id if isinstance(object_id, int) else None

    def _site_id_from_value(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return self._find_id("/api/dcim/sites/", "slug", value) or self._find_id(
                "/api/dcim/sites/", "name", value
            )
        return None

    def _rack_id_from_value(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return self._find_id("/api/dcim/racks/", "name", value)
        return None

    def _ensure_vrf(self, name: str) -> int | None:
        vrf_id = self._find_id("/api/ipam/vrfs/", "name", name)
        if vrf_id is not None:
            return vrf_id
        created = self._request(
            "POST",
            "/api/ipam/vrfs/",
            payload={"name": name},
        )
        object_id = created.get("id")
        return object_id if isinstance(object_id, int) else None

    def _prepare_desired(self, endpoint: str, desired: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            return desired

        prepared = dict(desired)

        if endpoint == "/api/dcim/sites/":
            region_name = prepared.get("region")
            if isinstance(region_name, str) and region_name.strip():
                region_id = self._ensure_region(region_name.strip())
                if region_id is not None:
                    prepared["region"] = region_id
            else:
                prepared.pop("region", None)
            # Avoid failures on instances where tags are restricted/unknown.
            prepared.pop("tags", None)

        elif endpoint == "/api/dcim/racks/":
            site_id = self._site_id_from_value(prepared.get("site"))
            if site_id is not None:
                prepared["site"] = site_id
            prepared.pop("custom_fields", None)

        elif endpoint == "/api/dcim/devices/":
            site_id = self._site_id_from_value(prepared.get("site"))
            if site_id is not None:
                prepared["site"] = site_id

            rack_id = self._rack_id_from_value(prepared.get("rack"))
            if rack_id is not None:
                prepared["rack"] = rack_id

            role_value = prepared.get("role")
            role_name = role_value if isinstance(role_value, str) else "gpu-compute"
            role_id = self._ensure_device_role(role_name)
            if role_id is not None:
                prepared["role"] = role_id

            if not prepared.get("device_type"):
                custom_fields = prepared.get("custom_fields")
                gpu_model = None
                if isinstance(custom_fields, dict):
                    model_val = custom_fields.get("gpu_model")
                    if isinstance(model_val, str) and model_val.strip():
                        gpu_model = model_val.strip().upper()
                device_type_id = self._ensure_device_type(
                    f"Generic GPU Node {gpu_model or 'H100'}"
                )
                if device_type_id is not None:
                    prepared["device_type"] = device_type_id

            prepared.pop("custom_fields", None)

        elif endpoint == "/api/ipam/vlans/":
            site_id = self._site_id_from_value(prepared.get("site"))
            if site_id is not None:
                prepared["site"] = site_id

        elif endpoint == "/api/ipam/prefixes/":
            status = prepared.get("status")
            if isinstance(status, str) and status == "planned":
                prepared["status"] = "active"
            vrf_value = prepared.get("vrf")
            if isinstance(vrf_value, str) and vrf_value.strip():
                vrf_id = self._ensure_vrf(vrf_value.strip())
                if vrf_id is not None:
                    prepared["vrf"] = vrf_id
                else:
                    prepared.pop("vrf", None)

        return prepared

    def upsert_payload(self, payload: NetBoxPayload) -> dict[str, Any]:
        """Upsert mapped NetBox payload with deterministic reconciliation summary."""

        result = {
            "status": "dry_run" if self.dry_run else "applied",
            "base_url": self.base_url,
            "reconciliation": {
                "sites": [],
                "racks": [],
                "devices": [],
                "vlans": [],
                "prefixes": [],
            },
        }

        had_errors = False

        def _safe_upsert(
            collection: str,
            endpoint: str,
            lookup_field: str,
            desired: dict[str, Any],
        ) -> None:
            nonlocal had_errors
            try:
                entry = self._upsert(endpoint, lookup_field, desired)
            except Exception as exc:  # noqa: BLE001
                had_errors = True
                entry = {
                    "action": "error",
                    "lookup": {lookup_field: desired.get(lookup_field)},
                    "error": str(exc),
                }
            result["reconciliation"][collection].append(entry)

        for site in payload.sites:
            _safe_upsert("sites", "/api/dcim/sites/", "slug", site)
        for rack in payload.racks:
            _safe_upsert("racks", "/api/dcim/racks/", "name", rack)
        for device in payload.devices:
            _safe_upsert("devices", "/api/dcim/devices/", "name", device)
        for vlan in payload.vlans:
            _safe_upsert("vlans", "/api/ipam/vlans/", "name", vlan)
        for prefix in payload.prefixes:
            _safe_upsert("prefixes", "/api/ipam/prefixes/", "prefix", prefix)

        if had_errors:
            result["status"] = "applied_with_errors" if not self.dry_run else "dry_run_with_errors"

        return result


def build_netbox_payload(sot: CanonicalSoT) -> NetBoxPayload:
    """Map canonical SoT into NetBox-friendly intent payloads."""
    site_slug = (sot.project.site_name or sot.project.project_name).lower().replace(" ", "-")
    deployment = sot.intent.deployment_name
    rack_name = f"{deployment}-rack-a"
    rack_height_u = 42
    device_u_height = 2

    devices: list[dict[str, Any]] = []
    for idx in range(sot.intent.node_count):
        # Fill the rack from the bottom up in 2U increments for a visible elevation layout.
        position = rack_height_u - (idx * device_u_height)
        devices.append(
            {
                "name": f"{deployment}-node-{idx+1}",
                "site": site_slug,
                "rack": rack_name,
                "status": "active",
                "role": "gpu-compute",
                "position": position,
                "face": "front",
                "custom_fields": {"gpu_model": sot.intent.gpu_model},
            }
        )

    return NetBoxPayload(
        sites=[
            {
                "name": sot.project.site_name or sot.project.project_name,
                "slug": site_slug,
                "region": sot.project.region,
                "tags": ["aidos", "intent"],
            }
        ],
        racks=[
            {
                "name": rack_name,
                "site": site_slug,
                "status": "active",
                "custom_fields": {"required_slots": sot.expected.required_rack_slots},
            }
        ],
        devices=devices,
        vlans=[
            {
                "name": f"{deployment}-vlan-{vlan}",
                "vid": int(vlan) if str(vlan).isdigit() else vlan,
                "site": site_slug,
            }
            for vlan in (sot.site.vlan_ids or sot.intent.required_vlans)
        ],
        prefixes=[
            {
                "prefix": "10.100.0.0/24",
                "site": site_slug,
                "vrf": f"{deployment}-vrf",
                "status": "planned",
            }
        ],
    )
