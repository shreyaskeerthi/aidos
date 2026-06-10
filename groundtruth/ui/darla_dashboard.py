"""Lightweight web dashboard for running Darla in browser."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from groundtruth.agents.darla import run_darla, write_outputs


class DarlaDashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for Darla dashboard pages and actions."""

    def _groundtruth_root(self) -> Path:
        return REPO_ROOT / "groundtruth"

    def _outputs_dir(self, project_slug: str | None = None) -> Path:
      base = self._groundtruth_root() / "outputs"
      if project_slug:
        return base / "projects" / project_slug
      return base

    def _project_store_path(self) -> Path:
      return self._outputs_dir() / "darla_projects.json"

    def _slugify(self, value: str) -> str:
      slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
      return slug or "project"

    def _default_project_catalog(self) -> dict:
        latest = self._latest_json_payload()
        project_name = str(latest.get("project", "Darla") or "Darla")
        project_slug = self._slugify(project_name)
        stakeholders = latest.get("ui_sections", {}).get("stakeholders", {}).get(
            "stakeholders", {}
        )
        return {
            "selected_project": project_slug,
            "projects": [
                {
                    "slug": project_slug,
                    "name": project_name,
                    "description": latest.get("objective", "Starter project"),
                    "contexts": [
                        {
                            "text": latest.get(
                                "customer_ask",
                                "Build a customer-ready Darla workspace.",
                            ),
                            "source": "seeded from latest run",
                        }
                    ],
                    "stakeholders": [
                        {
                            "name": role,
                            "role": role,
                            "note": data.get("note", ""),
                            "status": data.get("status", "unknown"),
                            "share_with": "",
                        }
                        for role, data in stakeholders.items()
                    ],
                }
            ],
        }

    def _load_project_store(self) -> dict:
      path = self._project_store_path()
      if not path.exists():
        store = self._default_project_catalog()
        self._save_project_store(store)
        return store
      try:
        store = json.loads(path.read_text(encoding="utf-8"))
      except json.JSONDecodeError:
        store = self._default_project_catalog()
        self._save_project_store(store)
        return store
      if not isinstance(store, dict):
        store = self._default_project_catalog()
      store.setdefault("selected_project", "")
      store.setdefault("projects", [])
      if not store["projects"]:
        store = self._default_project_catalog()
        self._save_project_store(store)
      return store

    def _save_project_store(self, store: dict) -> None:
      path = self._project_store_path()
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    def _resolve_project_slug(self, project_slug: str | None, store: dict | None = None) -> str:
        catalog = store or self._load_project_store()
        if project_slug:
            return project_slug
        selected = str(catalog.get("selected_project", "") or "")
        if selected:
            return selected
        projects = catalog.get("projects", [])
        if projects:
            return str(projects[0].get("slug", ""))
        return ""

    def _find_project(self, store: dict, project_slug: str) -> dict | None:
        for project in store.get("projects", []):
            if project.get("slug") == project_slug:
                return project
        return None

    def _latest_json_payload(self, project_slug: str | None = None) -> dict:
        latest_json = self._outputs_dir(project_slug) / "darla_latest.json"
        if not latest_json.exists():
            return {}
        try:
            return json.loads(latest_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send_text(
      self,
      body: str,
      *,
      content_type: str = "text/plain; charset=utf-8",
      status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
      encoded = body.encode("utf-8")
      self.send_response(status)
      self.send_header("Content-Type", content_type)
      self.send_header("Content-Length", str(len(encoded)))
      self.end_headers()
      self.wfile.write(encoded)

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _render_executive_brief(self, payload: dict) -> str:
      blockers = payload.get("blockers", [])
      blocker_text = (
        ", ".join(
          f"{item.get('category', 'Unknown')} ({item.get('severity', 'n/a')})"
          for item in blockers
        )
        if blockers
        else "No major blockers"
      )
      return (
        "DARLA EXECUTIVE BRIEF\n\n"
        f"Objective: {payload.get('objective', '')}\n"
        f"Average readiness: {payload.get('average_readiness', '-')}/100\n"
        f"Confidence: {payload.get('confidence', '-')}/100\n"
        f"Top risks: {blocker_text}\n"
      )

    def _render_engineering_checklist(self, payload: dict) -> str:
      actions = payload.get("next_actions", [])
      lines = [
        "ENGINEERING CHECKLIST",
        "",
        "[ ] Confirm deployment target and environment mode",
        "[ ] Validate data ingestion and document quality",
        "[ ] Confirm security controls and approval path",
        "[ ] Verify readiness blockers have owners",
      ]
      lines.extend(f"[ ] {action}" for action in actions[:4])
      return "\n".join(lines) + "\n"

    def _render_poc_plan(self, payload: dict) -> str:
      poc = {
        "project": payload.get("project", "Darla"),
        "objective": payload.get("objective", ""),
        "average_readiness": payload.get("average_readiness", 0),
        "confidence": payload.get("confidence", 0),
        "readiness": payload.get("readiness", {}),
        "blockers": payload.get("blockers", []),
        "next_actions": payload.get("next_actions", []),
        "ui_sections": payload.get("ui_sections", {}),
      }
      return json.dumps(poc, indent=2) + "\n"

    def _render_stakeholder_summary(self, payload: dict) -> str:
        stakeholder_section = payload.get("ui_sections", {}).get("stakeholders", {})
        stakeholders = stakeholder_section.get("stakeholders", {})
        risk_callout = stakeholder_section.get("risk_callout", "")
        lines = [
            "STAKEHOLDER SUMMARY",
            "",
            f"Risk callout: {risk_callout or 'None'}",
            "",
            "Key roles:",
        ]
        for role, data in stakeholders.items():
            lines.append(
                f"- {role}: {str(data.get('status', 'unknown')).upper()} - {data.get('note', '')}"
            )
        if len(lines) == 5:
            lines.append("- No stakeholder mapping available")
        return "\n".join(lines) + "\n"

    def _render_timeline_snapshot(self, payload: dict) -> str:
        timeline_section = payload.get("ui_sections", {}).get("timeline", {})
        phases = timeline_section.get("phases", [])
        summary = timeline_section.get("summary", "")
        lines = [
            "TIMELINE SNAPSHOT",
            "",
            f"Summary: {summary or 'None'}",
            "",
            "Phases:",
        ]
        for phase in phases:
            lines.append(
                f"- {phase.get('phase', '-')}: {str(phase.get('status', 'unknown')).upper()} ({phase.get('confidence', 'unknown')})"
            )
        if len(lines) == 5:
            lines.append("- No timeline data available")
        return "\n".join(lines) + "\n"

    def _render_docs_digest(self, payload: dict) -> str:
        documents = payload.get("ui_sections", {}).get("documents", {}).get("documents", [])
        lines = ["DOCUMENTS DIGEST", "", "Top evidence:"]
        for doc in documents[:5]:
            impacted = ", ".join(doc.get("impacted_categories", [])) or "none"
            lines.append(
                f"- {doc.get('source', '-')}: score {doc.get('score', 0)} | categories: {impacted}"
            )
            snippet = doc.get("top_snippet", "")
            if snippet:
                lines.append(f"  snippet: {snippet}")
        if len(lines) == 3:
            lines.append("- No document evidence available")
        return "\n".join(lines) + "\n"

    def _render_project_layer(self, store: dict, selected_slug: str) -> str:
        projects = store.get("projects", [])
        selected = self._find_project(store, selected_slug) or (projects[0] if projects else None)
        selected_name = selected.get("name", "No project selected") if selected else "No project selected"
        selected_description = selected.get("description", "Create a project to get started.") if selected else "Create a project to get started."
        contexts = selected.get("contexts", []) if selected else []
        stakeholders = selected.get("stakeholders", []) if selected else []
        current_slug = selected.get("slug", selected_slug or "") if selected else (selected_slug or "")

        cards = []
        for project in projects:
            slug = project.get("slug", "")
            active = "active" if slug == current_slug else ""
            cards.append(
                "<a class='project-card "
                + active
                + f"' href='/?project={quote_plus(slug)}'>"
                + f"<strong>{html.escape(str(project.get('name', slug or 'Project')))}</strong>"
                + f"<span>{html.escape(str(project.get('description', '')))}</span>"
                + "</a>"
            )

        context_items = "".join(
            "<li><strong>"
            + html.escape(str(item.get("source", "context")))
            + "</strong>: "
            + html.escape(str(item.get("text", "")))
            + "</li>"
            for item in contexts
        ) or "<li>No context added yet.</li>"

        stakeholder_items = "".join(
            "<li><strong>"
            + html.escape(str(item.get("name", item.get("role", "stakeholder"))))
            + "</strong> - "
            + html.escape(str(item.get("role", "")))
            + "<div class='muted'>"
            + html.escape(str(item.get("note", "")))
            + "</div></li>"
            for item in stakeholders
        ) or "<li>No stakeholders added yet.</li>"

        selected_input = html.escape(current_slug)
        return f"""
    <section class="card project-layer">
      <div class="project-layout">
        <div class="sub">
          <h3>Projects</h3>
          <div class="project-list">{''.join(cards) or '<div class="muted">No projects yet.</div>'}</div>
          <form method="post" action="/project/create" class="stack-form" style="margin-top:12px;">
            <label for="project-name">Create project</label>
            <input id="project-name" name="name" placeholder="New project name" required>
            <input name="description" placeholder="Project description" style="margin-top:8px;">
            <button type="submit" class="action-btn" style="margin-top:8px;">Add project</button>
          </form>
        </div>
        <div class="sub">
          <h3>{html.escape(selected_name)}</h3>
          <p class="muted">{html.escape(selected_description)}</p>
          <h4 style="margin:12px 0 6px;">Knowledgebase context</h4>
          <ul>{context_items}</ul>
          <form method="post" action="/project/context" class="stack-form" style="margin-top:12px;">
            <input type="hidden" name="project" value="{selected_input}">
            <label for="context-text">Add context</label>
            <textarea id="context-text" name="text" placeholder="Add project context, notes, links, or background" required></textarea>
            <input name="source" placeholder="Source label" style="margin-top:8px;">
            <button type="submit" class="action-btn" style="margin-top:8px;">Save context</button>
          </form>
          <h4 style="margin:16px 0 6px;">Shared stakeholders</h4>
          <ul>{stakeholder_items}</ul>
          <form method="post" action="/project/stakeholder" class="stack-form" style="margin-top:12px;">
            <input type="hidden" name="project" value="{selected_input}">
            <label for="stakeholder-name">Add stakeholder</label>
            <input id="stakeholder-name" name="name" placeholder="Name" required>
            <input name="role" placeholder="Role" style="margin-top:8px;" required>
            <input name="note" placeholder="Why they should be in the loop" style="margin-top:8px;">
            <input name="share_with" placeholder="Share with (comma-separated)" style="margin-top:8px;">
            <button type="submit" class="action-btn" style="margin-top:8px;">Share with stakeholder</button>
          </form>
        </div>
      </div>
    </section>
"""

    def _render_home(
        self,
        payload: dict,
        message: str = "",
        *,
        project_store: dict | None = None,
        selected_project: str = "",
    ) -> str:
        backend_mode = str(payload.get("backend_mode", "-") or "-")
        customer_ask = html.escape(str(payload.get("customer_ask", "") or ""))
        objective = html.escape(str(payload.get("objective", "") or ""))
        confidence = payload.get("confidence", 0)
        avg = payload.get("average_readiness", 0)
        gauge_label = str(payload.get("ui_sections", {}).get("gauge_label", ""))
        ui_sections_json = json.dumps(payload.get("ui_sections", {})).replace("</", "<\\/")
        catalog = project_store or self._load_project_store()
        current_project = self._resolve_project_slug(selected_project, catalog)
        project_layer_html = self._render_project_layer(catalog, current_project)
        project_query = f"&project={quote_plus(current_project)}" if current_project else ""
        message_html = (
            f"<div class='banner'>{html.escape(message)}</div>" if message else ""
        )

        template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Darla Web Dashboard</title>
  <style>
    :root {
      --bg: #081220;
      --panel: rgba(11, 24, 41, 0.9);
      --panel-2: rgba(9, 18, 33, 0.86);
      --border: rgba(103, 157, 255, 0.2);
      --text: #edf3ff;
      --muted: #9ab0cf;
      --accent: #58b4ff;
      --ok: #74eead;
      --warn: #ffca6c;
      --danger: #ff7d7d;
    }
    * { box-sizing: border-box; }
    a {
      text-decoration: none;
      color: #464feb;
    }
    tr th, tr td {
      border: 1px solid #e6e6e6;
    }
    tr th {
      background-color: #f5f5f5;
    }
    body {
      margin: 0;
      color: var(--text);
      font-family: \"IBM Plex Mono\", \"Courier Prime\", Consolas, \"Lucida Console\", Menlo, monospace;
      font-weight: 500;
      letter-spacing: 0.01em;
      background:
        radial-gradient(circle at 0% 0%, rgba(88, 180, 255, 0.2), transparent 25%),
        radial-gradient(circle at 100% 0%, rgba(108, 113, 255, 0.16), transparent 25%),
        linear-gradient(180deg, #07101b 0%, #081220 40%, #06101d 100%);
      min-height: 100vh;
      padding: 20px;
    }
    .shell { max-width: 1160px; margin: 0 auto; }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 16px 30px rgba(2, 6, 12, 0.45);
    }
    .header {
      display: grid;
      gap: 14px;
      grid-template-columns: 1.4fr 0.6fr;
      margin-bottom: 14px;
    }
    .header h1 { margin: 0 0 6px; font-size: 30px; }
    .meta { color: var(--muted); font-size: 13px; }
    .pill-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .pill {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 10px;
      background: rgba(11, 24, 41, 0.85);
      font-size: 12px;
      color: var(--muted);
    }
    .gauge { font-size: 24px; font-weight: 700; }
    .mode-toggle { display: flex; gap: 8px; margin-top: 10px; }
    .mode-btn {
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--muted);
      padding: 6px 10px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
    }
    .mode-btn.active {
      border-color: rgba(88, 180, 255, 0.7);
      color: var(--accent);
      background: rgba(88, 180, 255, 0.12);
    }
    .top-tabs {
      position: sticky;
      top: 8px;
      z-index: 8;
      display: flex;
      justify-content: flex-end;
      margin-bottom: 12px;
      padding: 0;
      background: transparent;
      border: 0;
      box-shadow: none;
    }
    .tabs {
      display: flex;
      gap: 12px;
      flex-wrap: nowrap;
      align-items: center;
      justify-content: flex-end;
      margin: 0;
      overflow-x: auto;
      white-space: nowrap;
      font-family: inherit;
    }
    .tabs::-webkit-scrollbar { height: 0; }
    .tab-btn {
      width: auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--muted);
      border-radius: 0;
      box-shadow: none;
      cursor: pointer;
      font-weight: 650;
      font-size: 12px;
      line-height: 1.2;
      letter-spacing: 0.03em;
      font-family: inherit;
    }
    .tab-btn.active {
      color: var(--accent);
      background: transparent;
      border-bottom: 2px solid rgba(88, 180, 255, 0.85);
      text-shadow: 0 0 14px rgba(88, 180, 255, 0.18);
    }
    .project-layer { margin-bottom: 14px; }
    .project-layout {
      display: grid;
      gap: 12px;
      grid-template-columns: 0.38fr 0.62fr;
    }
    .project-list { display: flex; flex-direction: column; gap: 8px; }
    .project-card {
      display: grid;
      gap: 4px;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      background: rgba(8, 16, 30, 0.72);
      color: var(--text);
    }
    .project-card span { color: var(--muted); font-size: 12px; }
    .project-card.active {
      border-color: rgba(88, 180, 255, 0.72);
      background: rgba(88, 180, 255, 0.12);
    }
    .stack-form input,
    .stack-form textarea {
      width: 100%;
      margin-top: 8px;
    }
    .agent-layout {
      display: grid;
      gap: 12px;
      grid-template-columns: 0.32fr 0.34fr 0.34fr;
    }
    .agent-card {
      text-align: left;
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel-2);
      color: var(--text);
      padding: 10px 12px;
      margin-bottom: 8px;
    }
    .agent-card.active { border-color: rgba(88, 180, 255, 0.72); background: rgba(88, 180, 255, 0.12); }
    .chat-log {
      max-height: 360px;
      overflow-y: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: rgba(8, 16, 30, 0.58);
      padding: 8px;
    }
    .gc-thread {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .gc-row {
      display: flex;
    }
    .gc-row.left { justify-content: flex-start; }
    .gc-row.right { justify-content: flex-end; }
    .gc-bubble {
      width: min(92%, 560px);
      border: 1px solid rgba(103, 157, 255, 0.24);
      background: rgba(10, 21, 37, 0.88);
      border-radius: 12px;
      padding: 8px 10px;
    }
    .gc-row.right .gc-bubble {
      background: rgba(25, 46, 79, 0.9);
      border-color: rgba(88, 180, 255, 0.34);
    }
    .gc-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;
    }
    .gc-name { color: var(--accent); font-size: 12px; font-weight: 700; }
    .gc-time { color: var(--muted); font-size: 11px; }
    .gc-line { margin: 4px 0 0; font-size: 13px; }
    .gc-why { margin: 6px 0 0; padding-left: 18px; }
    .chat-item {
      border: 1px solid rgba(103, 157, 255, 0.22);
      background: rgba(10, 21, 37, 0.78);
      border-radius: 8px;
      padding: 8px;
      margin-bottom: 8px;
    }
    .chat-speaker { color: var(--accent); font-size: 12px; font-weight: 700; margin-bottom: 4px; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .split { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
    .sub {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: var(--panel-2);
    }
    .sub h3 { margin: 0 0 8px; font-size: 15px; font-weight: 650; }
    .chip { display: inline-block; border-radius: 999px; padding: 4px 8px; font-size: 11px; font-weight: 700; }
    .chip.green { background: rgba(116, 238, 173, 0.18); color: var(--ok); }
    .chip.yellow { background: rgba(255, 202, 108, 0.16); color: var(--warn); }
    .chip.red { background: rgba(255, 125, 125, 0.16); color: var(--danger); }
    .risk-item { border-left: 3px solid rgba(103, 157, 255, 0.45); padding: 8px; border-radius: 8px; background: rgba(8, 16, 28, 0.72); }
    .risk-item + .risk-item { margin-top: 8px; }
    .thinking-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 8px;
    }
    .thinking-list {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      background: rgba(8, 16, 30, 0.55);
    }
    .thinking-list h4 {
      margin: 0 0 6px;
      font-size: 13px;
      color: var(--accent);
    }
    .feedback-item {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(8, 16, 30, 0.62);
      padding: 8px 10px;
      margin-bottom: 8px;
    }
    .doc-layout { display: grid; gap: 10px; grid-template-columns: 0.4fr 0.6fr; }
    .doc-list button {
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px;
      margin-bottom: 8px;
      background: var(--panel-2);
      color: var(--accent);
      cursor: pointer;
    }
    .doc-list button.active { border-color: rgba(88, 180, 255, 0.72); background: rgba(88, 180, 255, 0.14); }
    .agent-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-2);
    }
    .agent-row + .agent-row { margin-top: 8px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .action-btn {
      border: 1px solid rgba(88, 180, 255, 0.7);
      color: var(--accent);
      border-radius: 8px;
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(88, 180, 255, 0.1);
    }
    table { width: 100%; border-collapse: collapse; }
    tr th, tr td { padding: 7px; text-align: left; }
    ul { margin: 6px 0 0; padding-left: 18px; }
    .muted { color: var(--muted); }
    input:not([type="hidden"]), textarea, select, button {
      width: 100%;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: rgba(8, 16, 30, 0.75);
      color: var(--text);
      padding: 9px;
      font-size: 13px;
      font-family: inherit;
    }
    textarea { min-height: 96px; resize: vertical; }
    button { cursor: pointer; font-weight: 600; }
    .run-btn { background: linear-gradient(90deg, #2b7be7, #3eb4ff); border-color: transparent; }
    .banner { margin-bottom: 10px; border: 1px solid rgba(116, 238, 173, 0.35); color: var(--ok); border-radius: 8px; padding: 8px 10px; background: rgba(116, 238, 173, 0.08); }
    .run-bar { margin-top: 12px; }
    @media (max-width: 900px) {
      .header { grid-template-columns: 1fr; }
      .split { grid-template-columns: 1fr; }
      .thinking-grid { grid-template-columns: 1fr; }
      .doc-layout { grid-template-columns: 1fr; }
      .agent-layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class=\"shell\">
    <section class="card top-tabs">
      <div class="tabs">
        <button class="tab-btn active" data-tab="projects">Projects</button>
        <button class="tab-btn" data-tab="overview">Overview</button>
        <button class="tab-btn" data-tab="stakeholders">Stakeholders</button>
        <button class="tab-btn" data-tab="timeline">Timeline</button>
        <button class="tab-btn" data-tab="documents">Docs</button>
        <button class="tab-btn" data-tab="agents">Agents</button>
      </div>
    </section>

    <section class=\"header\">
      <article class=\"card\">
        <h1>GroundTruth Command Center</h1>
        <div class=\"meta\">Customer ask</div>
        <p>__CUSTOMER_ASK__</p>
        <div class=\"pill-row\">
          <span class=\"pill\">Objective: __OBJECTIVE__</span>
          <span class=\"pill\">Confidence: __CONFIDENCE__</span>
          <span class=\"pill\">Backend: __BACKEND__</span>
        </div>
      </article>
      <article class=\"card\">
        <div class=\"meta\">Readiness</div>
        <div class=\"gauge\">__READINESS__ - __GAUGE__</div>
        <div class=\"mode-toggle\">
          <button type=\"button\" class=\"mode-btn __PRACTICE_ACTIVE__\">Practice</button>
          <button type=\"button\" class=\"mode-btn __REAL_ACTIVE__\">Real</button>
          <button type=\"button\" class=\"mode-btn\">NVIDIA Stack</button>
        </div>
      </article>
    </section>

    __MESSAGE_BANNER__
    <section class=\"card\">
      <section class="tab-panel active" id="tab-projects">
        __PROJECT_LAYER__
      </section>

      <section class="tab-panel" id="tab-overview">
        <div class="split">
          <div class="sub">
            <h3>Readiness Scorecard</h3>
            <div id=\"overview-readiness\"></div>
          </div>
          <div class=\"sub\">
            <h3>Blockers</h3>
            <div id=\"overview-blockers\"></div>
            <h3 style=\"margin-top:12px;\">Top Recommendations</h3>
            <ul id=\"overview-recos\"></ul>
          </div>
        </div>
        <div class="sub" style="margin-top:12px;">
          <h3>DARLA Thinking Process</h3>
          <div class="thinking-grid">
            <div class="thinking-list"><h4>Decomposition</h4><ul id="thinking-decomposition"></ul></div>
            <div class="thinking-list"><h4>Decisions</h4><ul id="thinking-decisions"></ul></div>
            <div class="thinking-list"><h4>Priorities</h4><ul id="thinking-priorities"></ul></div>
            <div class="thinking-list"><h4>Justification</h4><ul id="thinking-justification"></ul></div>
          </div>
        </div>
        <div class="sub" style="margin-top:12px;">
          <h3>Live Evaluation Feedback</h3>
          <div id="evaluation-feedback"></div>
        </div>
      </section>

      <section class=\"tab-panel\" id=\"tab-stakeholders\">
        <div class=\"sub\">
          <h3>Stakeholders Map</h3>
          <table>
            <thead><tr><th>Role</th><th>Status</th><th>Signal</th></tr></thead>
            <tbody id=\"stakeholder-rows\"></tbody>
          </table>
          <p id=\"stakeholder-risk\" class=\"muted\" style=\"margin-top:10px;\"></p>
          <div class="actions" style="margin-top:10px;">
            <a class="action-btn" href="/action?type=stakeholder_summary">Generate Stakeholder Summary</a>
          </div>
        </div>
      </section>

      <section class=\"tab-panel\" id=\"tab-timeline\">
        <div class=\"sub\">
          <h3>Execution Timeline</h3>
          <table>
            <thead><tr><th>Phase</th><th>Status</th><th>Confidence</th></tr></thead>
            <tbody id=\"timeline-rows\"></tbody>
          </table>
          <div class="actions" style="margin-top:10px;">
            <a class="action-btn" href="/action?type=timeline_snapshot">Generate Timeline Snapshot</a>
          </div>
        </div>
      </section>

      <section class=\"tab-panel\" id=\"tab-documents\">
        <div class=\"doc-layout\">
          <div class=\"doc-list\" id=\"doc-list\"></div>
          <div class=\"sub\" id=\"doc-detail\">
            <h3>Select a document</h3>
            <p class=\"muted\">Snippet + impact mapping appears here.</p>
              <div class="actions" style="margin-top:10px;">
                <a class="action-btn" href="/action?type=docs_digest">Generate Docs Digest</a>
              </div>
            </div>
          </div>
        </section>

      <section class=\"tab-panel\" id=\"tab-agents\">
        <div class=\"agent-layout\">
          <div id=\"agent-rows\"></div>
          <div class=\"sub\" id=\"agent-detail\">
            <h3>Agent detail</h3>
            <p class=\"muted\">Click an agent to open its decision summary and working notes.</p>
          </div>
          <div class=\"sub\">
            <h3>Orchestration conversation</h3>
            <div id=\"agent-orchestration\" class=\"chat-log\"></div>
          </div>
        </div>
      </section>

      <div class=\"actions\">
        <a class=\"action-btn\" href=\"/action?type=executive_brief\">Generate Executive Brief</a>
        <a class=\"action-btn\" href=\"/action?type=engineering_checklist\">Generate Checklist</a>
        <a class=\"action-btn\" href=\"/action?type=poc_plan\">Export POC Plan</a>
      </div>

      <div class=\"run-bar\">
        <form method=\"post\" action=\"/run\">
          <input type=\"hidden\" name=\"project\" value=\"__PROJECT_SLUG__\">
          <label for=\"mode\">Mode</label>
          <select id=\"mode\" name=\"mode\">
            <option value=\"practice\" selected>practice (CPU-safe)</option>
            <option value=\"provisioned\">provisioned (requires NIM_BASE_URL + NIM_API_KEY)</option>
          </select>
          <br><br>
          <label for=\"ask\">Customer ask</label>
          <textarea id=\"ask\" name=\"ask\" required>Build a secure customer readiness RAG cockpit with citations and owner handoff.</textarea>
          <br><br>
          <button type=\"submit\" class=\"run-btn\">Run Darla</button>
        </form>
      </div>
    </section>
  </main>
  <script>
    const uiSections = __UI_SECTIONS_JSON__;

    function chip(status, text) {
      return '<span class="chip ' + status + '">' + text + '</span>';
    }

    function renderOverview() {
      const overview = uiSections.overview || {};
      const thinking = uiSections.thinking || {};
      const readiness = overview.readiness || {};
      const blockers = overview.blockers || [];
      const recos = overview.recommendations || [];
      const categoryFeedback = thinking.category_feedback || [];

      const trendIcon = (trend) => trend === 'up' ? '↑' : (trend === 'flat' ? '→' : '↓');

      const readinessRows = (categoryFeedback.length ? categoryFeedback : Object.entries(readiness).map((entry) => ({
        category: entry[0],
        score: entry[1],
        trend: 'flat',
      }))).map((item) => {
        return '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(103,157,255,0.15);"><strong>'
          + (item.category || '-')
          + '</strong><span>'
          + (item.score || 0)
          + ' '
          + trendIcon(item.trend || 'flat')
          + '</span></div>';
      }).join('');
      document.getElementById('overview-readiness').innerHTML = readinessRows || "<p class='muted'>No data</p>";

      const blockerHtml = blockers.map((b) => {
        const sev = b.severity || 'low';
        const chipColor = sev === 'high' ? 'red' : (sev === 'medium' ? 'yellow' : 'green');
        return '<div class="risk-item">' + chip(chipColor, sev.toUpperCase()) + ' <strong>' + (b.category || 'Unknown') + '</strong><div>' + (b.message || '') + '</div></div>';
      }).join('');
      document.getElementById('overview-blockers').innerHTML = blockerHtml || "<p class='muted'>No blockers</p>";
      document.getElementById('overview-recos').innerHTML = recos.slice(0, 3).map((item) => '<li>' + item + '</li>').join('') || '<li>None</li>';

      document.getElementById('thinking-decomposition').innerHTML = (thinking.decomposition || []).map((item) => '<li>' + item + '</li>').join('') || '<li>None</li>';
      document.getElementById('thinking-decisions').innerHTML = (thinking.decisions || []).map((item) => '<li>' + item + '</li>').join('') || '<li>None</li>';
      document.getElementById('thinking-priorities').innerHTML = (thinking.priorities || []).map((item) => '<li>' + item + '</li>').join('') || '<li>None</li>';
      document.getElementById('thinking-justification').innerHTML = (thinking.justification || []).map((item) => '<li>' + item + '</li>').join('') || '<li>None</li>';

      const feedbackHtml = categoryFeedback.map((item) => {
        const reasons = (item.reasons || []).map((reason) => '<li>' + reason + '</li>').join('') || '<li>No reasons captured</li>';
        return '<div class="feedback-item">'
          + '<div><strong>' + (item.category || '-') + '</strong>: ' + (item.score || 0) + ' ' + trendIcon(item.trend || 'flat') + '</div>'
          + '<ul>' + reasons + '</ul>'
          + '</div>';
      }).join('');
      document.getElementById('evaluation-feedback').innerHTML = feedbackHtml || "<p class='muted'>No evaluation feedback available.</p>";
    }

    function renderStakeholders() {
      const stakeholders = uiSections.stakeholders || {};
      const map = stakeholders.stakeholders || {};
      const rows = Object.entries(map).map((entry) => {
        const role = entry[0];
        const data = entry[1] || {};
        const status = data.status || 'red';
        return '<tr><td>' + role + '</td><td>' + chip(status, status.toUpperCase()) + '</td><td>' + (data.note || '') + '</td></tr>';
      }).join('');
      document.getElementById('stakeholder-rows').innerHTML = rows || "<tr><td colspan='3'>No data</td></tr>";
      document.getElementById('stakeholder-risk').textContent = stakeholders.risk_callout || '';
    }

    function renderTimeline() {
      const timeline = uiSections.timeline || {};
      const phases = timeline.phases || [];
      const rows = phases.map((phase) => {
        const status = phase.status || 'red';
        return '<tr><td>' + (phase.phase || '-') + '</td><td>' + chip(status, status.toUpperCase()) + '</td><td>' + (phase.confidence || 'Low') + '</td></tr>';
      }).join('');
      document.getElementById('timeline-rows').innerHTML = rows || "<tr><td colspan='3'>No timeline data</td></tr>";
    }

    function renderDocuments() {
      const docs = (uiSections.documents || {}).documents || [];
      const list = document.getElementById('doc-list');
      const detail = document.getElementById('doc-detail');

      function setDetail(doc) {
        const impacted = (doc.impacted_categories || []).map((category) => '<li>' + category + '</li>').join('') || '<li>No direct category mapping</li>';
        detail.innerHTML = '<h3>' + (doc.source || '-') + '</h3>'
          + '<p><strong>Score:</strong> ' + (doc.score || 0) + '</p>'
          + '<p><strong>Snippet:</strong><br>' + (doc.top_snippet || 'None') + '</p>'
          + '<ul>' + impacted + '</ul>';
      }

      list.innerHTML = '';
      docs.forEach((doc, idx) => {
        const btn = document.createElement('button');
        btn.textContent = doc.source;
        btn.className = idx === 0 ? 'active' : '';
        btn.addEventListener('click', () => {
          [...list.querySelectorAll('button')].forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          setDetail(doc);
        });
        list.appendChild(btn);
      });
      if (docs.length) {
        setDetail(docs[0]);
      }
    }

    function renderAgents() {
      const steps = (uiSections.agent_flow || {}).steps || [];
      const host = document.getElementById('agent-rows');
      const detail = document.getElementById('agent-detail');
      const orchestration = document.getElementById('agent-orchestration');

      function renderDetail(step) {
        const inputs = (step.inputs || []).map((item) => '<li>' + item + '</li>').join('') || '<li>No inputs listed</li>';
        const outputs = (step.outputs || []).map((item) => '<li>' + item + '</li>').join('') || '<li>No outputs listed</li>';
        const why = (step.why || []).map((item) => '<li>' + item + '</li>').join('') || '<li>No rationale listed</li>';
        const transcript = (step.transcript || []).map((turn) => {
          return '<div class="chat-item"><div class="chat-speaker">' + (turn.speaker || step.name || 'Agent') + '</div><div>' + (turn.message || '') + '</div></div>';
        }).join('') || '<div class="chat-item">No step transcript available.</div>';
        detail.innerHTML = '<h3>' + (step.name || '-') + '</h3>'
          + '<p><strong>Persona:</strong> ' + (step.persona || 'Agent') + '</p>'
          + '<p><strong>Background:</strong> ' + (step.background || 'General orchestration') + '</p>'
          + '<p><strong>What it did:</strong><br>' + (step.did || 'No task mapping available') + '</p>'
          + '<p><strong>Conclusion:</strong><br>' + (step.concluded || 'No conclusion available') + '</p>'
          + '<p><strong>Why:</strong></p><ul>' + why + '</ul>'
          + '<p><strong>Status:</strong> ' + (step.status || '-') + '</p>'
          + '<p><strong>Duration:</strong> ' + (step.duration_ms || 0) + ' ms</p>'
          + '<p><strong>Decision summary:</strong><br>' + (step.summary || 'No summary available') + '</p>'
          + '<p><strong>Inputs</strong></p><ul>' + inputs + '</ul>'
          + '<p><strong>Outputs</strong></p><ul>' + outputs + '</ul>'
          + '<p><strong>Local reasoning conversation</strong></p><div class="chat-log">' + transcript + '</div>';
      }

      host.innerHTML = steps.map((step, idx) => {
        const done = step.status === 'done';
        return '<button type="button" class="agent-card' + (idx === 0 ? ' active' : '') + '" data-agent-index="' + idx + '">'
          + '<div>' + (idx + 1) + '. ' + (step.name || '-') + '</div>'
          + '<div style="margin-top:6px;">' + chip(done ? 'green' : 'yellow', done ? 'DONE' : 'PENDING') + '</div>'
          + '</button>';
      }).join('');

      const cards = [...host.querySelectorAll('.agent-card')];
      cards.forEach((card) => {
        card.addEventListener('click', () => {
          cards.forEach((item) => item.classList.remove('active'));
          card.classList.add('active');
          const step = steps[Number(card.dataset.agentIndex || '0')] || steps[0] || {};
          renderDetail(step);
        });
      });

      if (steps.length) {
        renderDetail(steps[0]);
      }

      let elapsed = 0;
      const orchestrationTurns = steps.map((step, idx) => {
        elapsed += Number(step.duration_ms || 0);
        const transcript = step.transcript || [];
        const handoff = transcript.length > 1 ? transcript[1].message : (transcript[0] ? transcript[0].message : 'No handoff note recorded');
        return {
          speaker: step.name || 'Agent',
          did: step.did || 'No task mapping available',
          concluded: step.concluded || step.summary || 'No conclusion available',
          why: step.why || [],
          handoff,
          side: idx % 2 === 0 ? 'left' : 'right',
          time: '+' + elapsed + 'ms',
        };
      });

      if (orchestration) {
        orchestration.innerHTML = '<div class="gc-thread">' + (orchestrationTurns.map((turn) => {
          const why = (turn.why || []).slice(0, 3).map((item) => '<li>' + item + '</li>').join('') || '<li>No justification listed</li>';
          return '<div class="gc-row ' + turn.side + '">'
            + '<div class="gc-bubble">'
            + '<div class="gc-head"><span class="gc-name">' + turn.speaker + '</span><span class="gc-time">' + turn.time + '</span></div>'
            + '<p class="gc-line"><strong>Did:</strong> ' + turn.did + '</p>'
            + '<p class="gc-line"><strong>Decision:</strong> ' + turn.concluded + '</p>'
            + '<p class="gc-line"><strong>Why:</strong></p><ul class="gc-why">' + why + '</ul>'
            + '<p class="gc-line"><strong>Handoff:</strong> ' + turn.handoff + '</p>'
            + '</div>'
            + '</div>';
        }).join('') || '<div class="chat-item">No orchestration conversation available.</div>') + '</div>';
      }
    }

    function initTabs() {
      const buttons = [...document.querySelectorAll('.tab-btn')];
      const panels = [...document.querySelectorAll('.tab-panel')];
      buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
          buttons.forEach((b) => b.classList.remove('active'));
          panels.forEach((p) => p.classList.remove('active'));
          btn.classList.add('active');
          const target = document.getElementById('tab-' + btn.dataset.tab);
          if (target) {
            target.classList.add('active');
          }
        });
      });
    }

    renderOverview();
    renderStakeholders();
    renderTimeline();
    renderDocuments();
    renderAgents();
    initTabs();
  </script>
</body>
</html>
"""

        return (
            template.replace("__CUSTOMER_ASK__", customer_ask)
            .replace("__OBJECTIVE__", objective)
            .replace("__CONFIDENCE__", str(confidence))
            .replace("__BACKEND__", html.escape(backend_mode))
            .replace("__READINESS__", str(avg))
            .replace("__GAUGE__", html.escape(gauge_label))
            .replace("__PROJECT_LAYER__", project_layer_html)
            .replace("__PROJECT_SLUG__", current_project)
            .replace(
                "__PRACTICE_ACTIVE__",
                "active" if backend_mode == "practice" else "",
            )
            .replace(
                "__REAL_ACTIVE__",
                "active" if backend_mode == "provisioned" else "",
            )
            .replace("__MESSAGE_BANNER__", message_html)
            .replace("__UI_SECTIONS_JSON__", ui_sections_json)
            .replace("/action?type=executive_brief", f"/action?type=executive_brief{project_query}")
            .replace("/action?type=engineering_checklist", f"/action?type=engineering_checklist{project_query}")
            .replace("/action?type=poc_plan", f"/action?type=poc_plan{project_query}")
            .replace("/action?type=stakeholder_summary", f"/action?type=stakeholder_summary{project_query}")
            .replace("/action?type=timeline_snapshot", f"/action?type=timeline_snapshot{project_query}")
            .replace("/action?type=docs_digest", f"/action?type=docs_digest{project_query}")
        )

    def do_GET(self) -> None:
      parsed = urlparse(self.path)
      params = parse_qs(parsed.query)
      store = self._load_project_store()
      selected_project = self._resolve_project_slug(params.get("project", [""])[0], store)

      if parsed.path == "/":
        message = params.get("message", [""])[0]
        payload = self._latest_json_payload(selected_project) or self._latest_json_payload()
        self._send_html(
          self._render_home(
            payload,
            message=message,
            project_store=store,
            selected_project=selected_project,
          )
        )
        return

      if parsed.path == "/action":
        action_type = (params.get("type", [""])[0] or "").strip().lower()
        payload = self._latest_json_payload(selected_project) or self._latest_json_payload()
        if not payload:
          self.send_error(HTTPStatus.NOT_FOUND, "No latest report to export")
          return

        if action_type == "executive_brief":
          self._send_text(self._render_executive_brief(payload))
          return
        if action_type == "engineering_checklist":
          self._send_text(self._render_engineering_checklist(payload))
          return
        if action_type == "poc_plan":
          self._send_text(
            self._render_poc_plan(payload),
            content_type="application/json; charset=utf-8",
          )
          return
        if action_type == "stakeholder_summary":
          self._send_text(self._render_stakeholder_summary(payload))
          return
        if action_type == "timeline_snapshot":
          self._send_text(self._render_timeline_snapshot(payload))
          return
        if action_type == "docs_digest":
          self._send_text(self._render_docs_digest(payload))
          return

        self.send_error(HTTPStatus.BAD_REQUEST, "Unknown action type")
        return

      if parsed.path == "/latest":
        latest_html = self._outputs_dir(selected_project) / "darla_latest.html"
        if latest_html.exists():
          self._send_html(latest_html.read_text(encoding="utf-8"))
        else:
          self._send_html("<h1>No report yet</h1><p>Run Darla first from the form.</p>")
        return

      if parsed.path == "/latest.json":
        latest_json = self._outputs_dir(selected_project) / "darla_latest.json"
        if latest_json.exists():
          payload = latest_json.read_bytes()
          self.send_response(HTTPStatus.OK)
          self.send_header("Content-Type", "application/json; charset=utf-8")
          self.send_header("Content-Length", str(len(payload)))
          self.end_headers()
          self.wfile.write(payload)
        else:
          self.send_error(HTTPStatus.NOT_FOUND, "No latest JSON report yet")
        return

      self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(raw)
        store = self._load_project_store()

        if parsed.path == "/project/create":
            name = (form.get("name", [""])[0] or "").strip()
            description = (form.get("description", [""])[0] or "").strip()
            if not name:
                self._redirect_with_message("Project name is required")
                return

            slug = self._slugify(name)
            if self._find_project(store, slug):
                slug = f"{slug}-{len(store.get('projects', [])) + 1}"

            store.setdefault("projects", []).append(
                {
                    "slug": slug,
                    "name": name,
                    "description": description or "New project workspace",
                    "contexts": [],
                    "stakeholders": [],
                }
            )
            store["selected_project"] = slug
            self._save_project_store(store)
            self._redirect_with_message(f"Created project {name}", slug)
            return

        if parsed.path == "/project/context":
            project_slug = self._resolve_project_slug(
                (form.get("project", [""])[0] or "").strip(), store
            )
            project = self._find_project(store, project_slug)
            if not project:
                self._redirect_with_message("Select a project first", project_slug)
                return

            text = (form.get("text", [""])[0] or "").strip()
            if not text:
                self._redirect_with_message("Context text is required", project_slug)
                return

            project.setdefault("contexts", []).append(
                {
                    "text": text,
                    "source": (form.get("source", [""])[0] or "manual").strip() or "manual",
                }
            )
            store["selected_project"] = project_slug
            self._save_project_store(store)
            self._redirect_with_message("Saved project context", project_slug)
            return

        if parsed.path == "/project/stakeholder":
            project_slug = self._resolve_project_slug(
                (form.get("project", [""])[0] or "").strip(), store
            )
            project = self._find_project(store, project_slug)
            if not project:
                self._redirect_with_message("Select a project first", project_slug)
                return

            name = (form.get("name", [""])[0] or "").strip()
            role = (form.get("role", [""])[0] or "").strip()
            if not name or not role:
                self._redirect_with_message(
                    "Stakeholder name and role are required", project_slug
                )
                return

            project.setdefault("stakeholders", []).append(
                {
                    "name": name,
                    "role": role,
                    "note": (form.get("note", [""])[0] or "").strip(),
                    "share_with": (form.get("share_with", [""])[0] or "").strip(),
                }
            )
            store["selected_project"] = project_slug
            self._save_project_store(store)
            self._redirect_with_message("Saved stakeholder", project_slug)
            return

        if parsed.path == "/run":
            ask = (form.get("ask", [""])[0] or "").strip()
            mode = (form.get("mode", ["practice"])[0] or "practice").strip().lower()
            project_slug = self._resolve_project_slug(
                (form.get("project", [""])[0] or "").strip(), store
            )

            if not ask:
                self._redirect_with_message("Customer ask is required", project_slug)
                return

            old_mode = os.environ.get("PROVISIONED_MODE")
            try:
                os.environ["PROVISIONED_MODE"] = "true" if mode == "provisioned" else "false"
                result = run_darla(ask, self._groundtruth_root())
                write_outputs(result, self._outputs_dir())
                write_outputs(result, self._outputs_dir(project_slug))
                store["selected_project"] = project_slug
                self._save_project_store(store)
                self._redirect_with_message(
                    f"Run completed in {result.backend_mode} mode with confidence {result.confidence}/100",
                    project_slug,
                )
            except RuntimeError as exc:
                self._redirect_with_message(str(exc), project_slug)
            finally:
                if old_mode is None:
                    os.environ.pop("PROVISIONED_MODE", None)
                else:
                    os.environ["PROVISIONED_MODE"] = old_mode
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _redirect_with_message(self, message: str, project_slug: str = "") -> None:
        target = f"/?message={quote_plus(message)}"
        if project_slug:
            target = f"/?project={quote_plus(project_slug)}&message={quote_plus(message)}"
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        self.end_headers()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Darla web dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="Port to bind (default: 8787)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DarlaDashboardHandler)
    print(f"Darla dashboard running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
