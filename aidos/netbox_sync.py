"""NetBox mapping, reconciliation, and sync client for AIDOS."""

from __future__ import annotations

import os
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
                "status": "planned",
                "custom_fields": {"required_slots": sot.expected.required_rack_slots},
            }
        ],
        devices=[
            {
                "name": f"{deployment}-node-{idx+1}",
                "site": site_slug,
                "rack": rack_name,
                "status": "planned",
                "role": "gpu-compute",
                "custom_fields": {"gpu_model": sot.intent.gpu_model},
            }
            for idx in range(sot.intent.node_count)
        ],
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
