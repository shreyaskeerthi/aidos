"""Project catalog and project-scoped output directory management for AIDOS."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aidos.state_store import JsonStateStore


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


class ProjectStore:
    """Persistent project catalog for multi-project operator workflows."""

    def __init__(self, root_output_dir: str = "aidos/outputs") -> None:
        self.root = Path(root_output_dir)
        self.catalog_path = self.root / "projects.json"
        self._store = JsonStateStore(self.catalog_path)

    def _read_catalog(self) -> dict[str, Any]:
        payload = self._store.read()
        payload.setdefault("projects", [])
        payload.setdefault("selected_project", "")
        return payload

    def _write_catalog(self, payload: dict[str, Any]) -> None:
        self._store.write(payload)

    def list_projects(self) -> list[dict[str, Any]]:
        return self._read_catalog().get("projects", [])

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        catalog = self._read_catalog()
        existing = catalog.get("projects", [])

        base_slug = _slugify(name)
        slug = base_slug
        taken = {item.get("id") for item in existing if isinstance(item, dict)}
        idx = 2
        while slug in taken:
            slug = f"{base_slug}-{idx}"
            idx += 1

        project = {
            "id": slug,
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(self.project_output_dir(slug)),
        }
        existing.append(project)
        catalog["projects"] = existing
        catalog["selected_project"] = slug
        self._write_catalog(catalog)

        self.project_output_dir(slug).mkdir(parents=True, exist_ok=True)
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        for project in self.list_projects():
            if project.get("id") == project_id:
                return project
        return None

    def select_project(self, project_id: str) -> None:
        catalog = self._read_catalog()
        catalog["selected_project"] = project_id
        self._write_catalog(catalog)

    def selected_project(self) -> str:
        return str(self._read_catalog().get("selected_project", "") or "")

    def project_output_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id
