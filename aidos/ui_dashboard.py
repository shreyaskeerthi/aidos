"""Operator-focused dashboard summary and HTML renderer for AIDOS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_ARTIFACT_DESCRIPTIONS: dict[str, tuple[int, str]] = {
    "canonical_sot.json": (
        1,
        "Canonical source of truth built from intake, intent, and site context.",
    ),
    "validation_report.json": (
        2,
        "Deterministic validation findings with readiness status and recommendations.",
    ),
    "missing_data_report.json": (
        3,
        "Gaps or incomplete intake data that need operator follow-up.",
    ),
    "netbox_sync_payloads.json": (
        4,
        "Planned infrastructure objects and optional reconciliation results.",
    ),
    "runbook.yaml": (
        5,
        "Execution plan of tasks, intent, preconditions, and approval requirements.",
    ),
    "agentic_task_graph.json": (
        6,
        "Task graph representation used for orchestration and execution flow.",
    ),
    "ansible_playbook.yml": (
        7,
        "Top-level playbook for infrastructure/provisioning automation steps.",
    ),
    "ansible_bundle/site.yml": (
        8,
        "Ansible bundle entrypoint that imports or orchestrates component playbooks.",
    ),
    "evidence_bundle.json": (
        9,
        "Audit trail of lifecycle evidence from intake through execution.",
    ),
    "observed_state_snapshot.json": (
        10,
        "Observed post-run state snapshot used for verification and comparison.",
    ),
    "post_execution_verification_report.json": (
        11,
        "Post-execution verification outcomes against expected intent.",
    ),
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_latest_summary(output_dir: str = "aidos/outputs") -> dict[str, Any]:
    """Build latest operator summary from generated artifacts."""
    root = Path(output_dir)
    latest = root / "latest"

    validation = _load_json(latest / "validation_report.json")
    observed = _load_json(latest / "observed_state_snapshot.json")
    approvals = _load_json(root / "state" / "approvals.json")

    executed = observed.get("signals", {}).get("executed_tasks", [])
    if not isinstance(executed, list):
        executed = []

    completed = sum(1 for item in executed if item.get("status") == "completed")
    blocked_pending = sum(
        1 for item in executed if item.get("status") == "blocked_pending_approval"
    )
    blocked_rejected = sum(
        1 for item in executed if item.get("status") == "blocked_rejected"
    )

    return {
        "deployment": validation.get("deployment", "unknown"),
        "readiness": validation.get("readiness", "unknown"),
        "critical": len(validation.get("critical", [])),
        "warning": len(validation.get("warning", [])),
        "passed": len(validation.get("passed", [])),
        "execution": {
            "total": len(executed),
            "completed": completed,
            "blocked_pending_approval": blocked_pending,
            "blocked_rejected": blocked_rejected,
            "records": executed,
        },
        "approvals": approvals if isinstance(approvals, dict) else {},
        "latest_dir": str(latest),
    }


def list_latest_artifacts(output_dir: str) -> list[dict[str, Any]]:
    """List latest artifacts for browsing and downloads."""
    latest = Path(output_dir) / "latest"
    if not latest.exists():
        return []

    artifacts: list[dict[str, Any]] = []
    for path in sorted(latest.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(latest).as_posix()
        if "netbox" in rel.lower():
            continue
        order, blurb = _ARTIFACT_DESCRIPTIONS.get(
            rel,
            _ARTIFACT_DESCRIPTIONS.get(path.name, (999, "Generated lifecycle artifact.")),
        )
        artifacts.append(
            {
                "name": rel,
                "size": path.stat().st_size,
                "path": str(path),
                "order": order,
                "blurb": blurb,
            }
        )
    artifacts.sort(key=lambda item: (int(item.get("order", 999)), str(item.get("name", ""))))
    return artifacts


def render_dashboard_html(summary: dict[str, Any]) -> str:
    """Render a simple operator-focused HTML dashboard."""
    execution_rows = "".join(
        [
            (
                "<tr>"
                f"<td>{item.get('task_id', '-')}</td>"
                f"<td>{item.get('executor', '-')}</td>"
                f"<td>{item.get('status', '-')}</td>"
                "</tr>"
            )
            for item in summary.get("execution", {}).get("records", [])
        ]
    )
    if not execution_rows:
        execution_rows = "<tr><td colspan='3'>No execution records</td></tr>"

    approval_rows = ""
    approvals = summary.get("approvals", {})
    if isinstance(approvals, dict):
        for task_id, item in approvals.items():
            if not isinstance(item, dict):
                continue
            approval_rows += (
                "<tr>"
                f"<td>{task_id}</td>"
                f"<td>{item.get('status', '-')}</td>"
                f"<td>{item.get('reviewer', '-')}</td>"
                f"<td>{item.get('reason', '-')}</td>"
                "</tr>"
            )
    if not approval_rows:
        approval_rows = "<tr><td colspan='4'>No approvals recorded</td></tr>"

    return f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>AIDOS Operator Dashboard</title>
  <style>
    body {{ font-family: Segoe UI, Tahoma, sans-serif; background: #f4f7fb; color: #122; margin: 0; }}
    .hero {{ background: linear-gradient(120deg, #0f2d52, #1d4f91); color: #fff; padding: 18px 24px; }}
    .wrap {{ padding: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 10px rgba(10,20,40,0.08); padding: 14px; }}
    .kpi {{ font-size: 30px; font-weight: 700; }}
    .label {{ color: #456; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .tables {{ padding: 0 20px 20px; display: grid; grid-template-columns: 1fr; gap: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 2px 10px rgba(10,20,40,0.08); border-radius: 10px; overflow: hidden; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e5ebf2; text-align: left; font-size: 13px; }}
    th {{ background: #eef3fb; }}
    .footer {{ padding: 12px 20px; color: #567; font-size: 12px; }}
  </style>
</head>
<body>
  <div class='hero'>
    <h2>AIDOS Operator Dashboard</h2>
    <div>Deployment: {summary.get("deployment", "unknown")} | Readiness: {summary.get("readiness", "unknown")}</div>
  </div>
  <div class='wrap'>
    <div class='card'><div class='label'>Critical</div><div class='kpi'>{summary.get("critical", 0)}</div></div>
    <div class='card'><div class='label'>Warnings</div><div class='kpi'>{summary.get("warning", 0)}</div></div>
    <div class='card'><div class='label'>Passed</div><div class='kpi'>{summary.get("passed", 0)}</div></div>
    <div class='card'><div class='label'>Executed</div><div class='kpi'>{summary.get("execution", {}).get("completed", 0)}</div></div>
    <div class='card'><div class='label'>Blocked Pending</div><div class='kpi'>{summary.get("execution", {}).get("blocked_pending_approval", 0)}</div></div>
    <div class='card'><div class='label'>Blocked Rejected</div><div class='kpi'>{summary.get("execution", {}).get("blocked_rejected", 0)}</div></div>
  </div>
  <div class='tables'>
    <table>
      <thead><tr><th colspan='3'>Execution Records</th></tr><tr><th>Task</th><th>Executor</th><th>Status</th></tr></thead>
      <tbody>{execution_rows}</tbody>
    </table>
    <table>
      <thead><tr><th colspan='4'>Approvals</th></tr><tr><th>Task</th><th>Status</th><th>Reviewer</th><th>Reason</th></tr></thead>
      <tbody>{approval_rows}</tbody>
    </table>
  </div>
  <div class='footer'>Source: {summary.get("latest_dir", "n/a")}</div>
</body>
</html>
"""


def render_operator_app_html() -> str:
        """Render interactive multi-project AIDOS operator application UI."""
        return """
<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>AIDOS Operator Console</title>
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
        body {
            margin: 0;
            color: var(--text);
            font-family: "IBM Plex Mono", "Courier Prime", Consolas, "Lucida Console", Menlo, monospace;
            background:
                radial-gradient(circle at 0% 0%, rgba(88, 180, 255, 0.2), transparent 25%),
                radial-gradient(circle at 100% 0%, rgba(108, 113, 255, 0.16), transparent 25%),
                linear-gradient(180deg, #07101b 0%, #081220 40%, #06101d 100%);
            min-height: 100vh;
        }
        .shell { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
        .sidebar { border-right: 1px solid var(--border); background: var(--panel-2); padding: 16px; }
        .main { padding: 16px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 12px; margin-bottom: 12px; }
        .title { margin: 0 0 8px; }
        .project-item { padding: 8px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; cursor: pointer; }
        .project-item.active { border-color: var(--accent); background: rgba(88, 180, 255, 0.12); }
        .muted { color: var(--muted); font-size: 12px; }
        input, textarea, select, button {
            width: 100%; margin-top: 6px; margin-bottom: 8px; border-radius: 8px;
            border: 1px solid var(--border); background: rgba(8,16,30,0.72); color: var(--text);
            padding: 8px; font-family: inherit;
        }
        button { cursor: pointer; }
        .btn-primary { background: linear-gradient(90deg, #2b7be7, #3eb4ff); border-color: transparent; color: #fff; }
        .kpis { display: grid; grid-template-columns: repeat(6, minmax(90px,1fr)); gap: 8px; }
        .kpi { background: rgba(8,16,30,0.62); border: 1px solid var(--border); border-radius: 10px; padding: 8px; }
        .kpi .v { font-size: 22px; font-weight: 700; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .list a { color: var(--accent); text-decoration: none; }
        .chat-log {
            max-height: 340px;
            overflow: auto;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 10px;
            background: rgba(5, 13, 26, 0.72);
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .chat-item {
            max-width: 88%;
            padding: 10px 12px;
            border-radius: 12px;
            border: 1px solid var(--border);
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.45;
        }
        .chat-item .chat-role {
            font-size: 11px;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: var(--muted);
            margin-bottom: 4px;
            display: block;
        }
        .chat-item.you {
            margin-left: auto;
            background: linear-gradient(180deg, rgba(63, 167, 255, 0.26), rgba(23, 95, 171, 0.2));
        }
        .chat-item.aidos,
        .chat-item.nemosys {
            margin-right: auto;
            background: rgba(116, 238, 173, 0.14);
        }
        .chat-item.system {
            margin-right: auto;
            background: rgba(255, 202, 108, 0.12);
        }
        .trace {
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px dashed var(--border);
            font-size: 12px;
            line-height: 1.4;
            color: #d8e6ff;
        }
        .trace .trace-title {
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-size: 11px;
            margin-bottom: 4px;
        }
        .trace .trace-chip {
            display: inline-block;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 2px 8px;
            margin: 2px 6px 2px 0;
            background: rgba(88, 180, 255, 0.1);
            color: #e8f2ff;
            font-size: 11px;
        }
        .artifact-item {
            position: relative;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 8px;
            margin-bottom: 8px;
            background: rgba(8,16,30,0.52);
        }
        .artifact-item .artifact-meta { color: var(--muted); font-size: 11px; }
        .artifact-item .artifact-blurb {
            display: none;
            position: absolute;
            left: 10px;
            right: 10px;
            top: calc(100% + 4px);
            z-index: 20;
            background: rgba(6, 14, 29, 0.97);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 8px;
            color: var(--text);
            font-size: 12px;
            line-height: 1.35;
            box-shadow: 0 6px 24px rgba(0, 0, 0, 0.32);
        }
        .artifact-item:hover .artifact-blurb { display: block; }
        .row { display: flex; gap: 8px; }
        .row > * { flex: 1; }
        .stage-grid {
            display: grid;
            grid-template-columns: repeat(7, minmax(100px, 1fr));
            gap: 8px;
            margin-top: 8px;
        }
        .stage {
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 6px;
            background: rgba(8,16,30,0.5);
            font-size: 11px;
            text-align: center;
            color: var(--muted);
        }
        .stage.active {
            color: #fff;
            border-color: var(--accent);
            background: rgba(88, 180, 255, 0.2);
        }
        .stage.done {
            color: #fff;
            border-color: var(--ok);
            background: rgba(116, 238, 173, 0.2);
        }
        .stage.error {
            color: #fff;
            border-color: var(--danger);
            background: rgba(255, 125, 125, 0.2);
        }
        .event-log {
            margin-top: 8px;
            max-height: 170px;
            overflow: auto;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: rgba(5, 13, 26, 0.72);
            padding: 8px;
        }
        .event-row {
            font-size: 12px;
            color: var(--text);
            margin-bottom: 6px;
            line-height: 1.35;
            white-space: pre-wrap;
        }
        .event-row .t { color: var(--muted); margin-right: 6px; }
        .insight {
            margin-top: 8px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: rgba(8,16,30,0.45);
            padding: 10px;
            font-size: 13px;
            line-height: 1.45;
            white-space: pre-wrap;
        }
        .warning-banner {
            border: 1px solid rgba(255, 202, 108, 0.4);
            background: rgba(255, 202, 108, 0.12);
            border-radius: 10px;
            padding: 10px;
            color: #ffe9b8;
            font-size: 12px;
            line-height: 1.45;
            margin-top: 8px;
        }
        .warning-banner.hidden { display: none; }
        .welcome-modal {
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(2, 6, 14, 0.72);
            z-index: 1000;
            padding: 20px;
        }
        .welcome-modal.show { display: flex; }
        .welcome-panel {
            width: min(680px, 100%);
            background: rgba(8, 16, 30, 0.98);
            border: 1px solid var(--border);
            border-radius: 16px;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
            padding: 18px;
            position: relative;
        }
        .welcome-close {
            position: absolute;
            top: 12px;
            right: 12px;
            width: 36px;
            height: 36px;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: rgba(255,255,255,0.06);
            color: var(--text);
            font-size: 18px;
            line-height: 1;
        }
        .welcome-panel h3 { margin-top: 0; }
        .welcome-panel p { color: var(--muted); line-height: 1.5; }
        @media (max-width: 1100px) {
            .shell { grid-template-columns: 1fr; }
            .grid { grid-template-columns: 1fr; }
            .kpis { grid-template-columns: repeat(3, minmax(90px,1fr)); }
            .stage-grid { grid-template-columns: repeat(3, minmax(100px, 1fr)); }
        }
    </style>
</head>
<body>
    <div class='welcome-modal show' id='welcome-modal' role='dialog' aria-modal='true' aria-labelledby='welcome-title'>
        <div class='welcome-panel'>
            <button class='welcome-close' type='button' aria-label='Close welcome dialog' onclick='closeWelcome()'>x</button>
            <h3 id='welcome-title'>Welcome to AIDOS</h3>
            <p>AIDOS is the deployment operating system. NeMoSys is the agentic operator assistant inside it, and it uses the NemoClaw task graph to reason about workflow stages, actions, and evidence.</p>
            <p>Use the project panel on the left, then upload survey/BOM/workload files or point to paths directly. Run the flow to see live stages, artifacts, NeMoSys reasoning traces, and execution evidence.</p>
            <p id='welcome-pyats-note'>If you want pyATS health checks, run AIDOS on Linux or WSL. Windows environments can still use the CLI fallback path.</p>
            <p>Thanks for using it.</p>
        </div>
    </div>
    <div class='shell'>
        <aside class='sidebar'>
            <h2 class='title'>AIDOS Projects</h2>
            <div id='project-list'></div>
            <div class='card'>
                <strong>New Project</strong>
                <input id='new-project-name' placeholder='Project name'>
                <textarea id='new-project-desc' placeholder='Description'></textarea>
                <button class='btn-primary' onclick='createProject()'>Create Project</button>
            </div>
        </aside>
        <main class='main'>
            <div class='card'>
                <h2 id='project-title'>Select a project</h2>
                <div class='muted' id='project-meta'>No project selected</div>
            </div>

            <div class='card'>
                <h3>Intake / Run Flow</h3>
                <div class='muted'>Upload files or provide paths directly.</div>
                <div class='row'>
                    <input type='file' id='file-survey'>
                    <input type='file' id='file-bom'>
                </div>
                <div class='row'>
                    <input type='file' id='file-workload'>
                    <input type='file' id='file-context'>
                </div>
                <button onclick='uploadInputs()'>Upload Selected Files To Project</button>
                <div class='row'>
                    <input id='survey-path' placeholder='Survey path (json/csv/xlsx)'>
                    <input id='workload-path' placeholder='Workload path (optional)'>
                </div>
                <div class='row'>
                    <input id='bom-path' placeholder='BOM path (optional if workload provided)'>
                    <input id='context-path' placeholder='Context path (optional)'>
                </div>
                <div class='row'>
                    <input id='pyats-testbed-path' placeholder='pyATS testbed path (optional for network health checks)'>
                </div>
                <div class='warning-banner hidden' id='pyats-warning'>pyATS is not supported in this Windows browser/session. AIDOS will fall back to CLI-based health checks unless you run in Linux or WSL.</div>
                <div class='row'>
                    <button onclick='fillDemoPaths()'>Use Demo Paths</button>
                    <button onclick='fillWesterbyPaths()'>Use Westerby Paths</button>
                    <button onclick='clearIntakeState()'>Clear Intake State</button>
                    <div id='flow-error' class='muted' style='align-self:center;'></div>
                </div>
                <div class='row'>
                    <label><input type='checkbox' id='execute-flow'> Execute</label>
                    <label><input type='checkbox' id='auto-approve'> Auto-approve</label>
                </div>
                <button class='btn-primary' onclick='runFlow()'>Run Project Flow</button>
            </div>

            <div class='card'>
                <h3>Status</h3>
                <div class='kpis'>
                    <div class='kpi'><div class='muted'>Readiness</div><div class='v' id='k-readiness'>-</div></div>
                    <div class='kpi'><div class='muted'>Critical</div><div class='v' id='k-critical'>0</div></div>
                    <div class='kpi'><div class='muted'>Warnings</div><div class='v' id='k-warning'>0</div></div>
                    <div class='kpi'><div class='muted'>Passed</div><div class='v' id='k-passed'>0</div></div>
                    <div class='kpi'><div class='muted'>Executed</div><div class='v' id='k-executed'>0</div></div>
                    <div class='kpi'><div class='muted'>Pending Approvals</div><div class='v' id='k-pending'>0</div></div>
                </div>
                <div class='insight' id='status-insight'>Run a flow to see a plain-English execution summary.</div>
            </div>

            <div class='card'>
                <h3>Run Timeline</h3>
                <div class='muted'>Live stages while flow is running.</div>
                <div class='stage-grid' id='stage-grid'>
                    <div class='stage' data-stage='intake'>Intake</div>
                    <div class='stage' data-stage='formalize'>Formalize</div>
                    <div class='stage' data-stage='validate'>Validate</div>
                    <div class='stage' data-stage='plan'>Plan</div>
                    <div class='stage' data-stage='execute'>Execute</div>
                    <div class='stage' data-stage='verify'>Verify</div>
                </div>
                <div class='event-log' id='event-log'></div>
            </div>

            <div class='grid'>
                <div class='card'>
                    <h3>Artifacts (View / Download)</h3>
                    <div class='list' id='artifact-list'></div>
                </div>
                <div class='card'>
                    <h3>NeMoSys Chat</h3>
                    <input id='chat-session' placeholder='Session id' value='ops-default'>
                    <label class='muted'><input type='checkbox' id='show-trace' checked> Show reasoning trace</label>
                    <div class='chat-log' id='chat-log'></div>
                    <input id='chat-input' placeholder='Ask about project status, findings, runbooks...'>
                    <button class='btn-primary' onclick='sendChat()'>Send</button>
                </div>
            </div>
        </main>
    </div>

    <script>
        let currentProject = null;
        let runInProgress = false;
        const WINDOWS_PYATS_UNSUPPORTED = navigator.userAgent.toLowerCase().includes('windows');

        const STAGES = ['intake', 'formalize', 'validate', 'plan', 'execute', 'verify'];

        function nowTime() {
            return new Date().toLocaleTimeString();
        }

        function addEvent(text) {
            const log = document.getElementById('event-log');
            const row = document.createElement('div');
            row.className = 'event-row';
            row.innerHTML = `<span class='t'>[${nowTime()}]</span>${escapeHtml(text)}`;
            log.appendChild(row);
            log.scrollTop = log.scrollHeight;
        }

        function setStage(stage, state) {
            const el = document.querySelector(`.stage[data-stage='${stage}']`);
            if (!el) return;
            el.classList.remove('active', 'done', 'error');
            if (state) el.classList.add(state);
        }

        function resetStages() {
            for (const stage of STAGES) {
                setStage(stage, null);
            }
        }

        function markDoneThrough(targetStage) {
            for (const stage of STAGES) {
                if (stage === targetStage) {
                    setStage(stage, 'active');
                    break;
                }
                setStage(stage, 'done');
            }
        }

        function escapeHtml(text) {
            return String(text)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;');
        }

        function addChat(role, text) {
            const log = document.getElementById('chat-log');
            const item = document.createElement('div');
            const cssRole = (role === 'you' || role === 'nemosys' || role === 'system') ? role : 'system';
            const safeRole = escapeHtml(role === 'system' ? 'NeMoSys' : role);
            const safeText = escapeHtml(text);
            item.className = `chat-item ${cssRole}`;
            item.innerHTML = `<span class='chat-role'>${safeRole}</span><div>${safeText}</div>`;
            log.appendChild(item);
            log.scrollTop = log.scrollHeight;
        }

        function addAssistantAnswer(answer) {
            const log = document.getElementById('chat-log');
            const item = document.createElement('div');
            item.className = 'chat-item nemosys';
            const message = escapeHtml(answer?.message || '(no response)');
            let html = `<span class='chat-role'>NeMoSys</span><div>${message}</div>`;

            const showTrace = document.getElementById('show-trace')?.checked;
            if (showTrace) {
                const cited = Array.isArray(answer?.cited_artifacts) ? answer.cited_artifacts : [];
                const actions = Array.isArray(answer?.proposed_actions) ? answer.proposed_actions : [];

                let traceHtml = "<div class='trace'><div class='trace-title'>Reasoning Trace</div>";
                traceHtml += "<div>NeMoSys grounded this answer in current AIDOS artifacts, workflow state, and the NemoClaw task graph.</div>";
                if (cited.length > 0) {
                    traceHtml += "<div style='margin-top:6px'><span class='trace-title'>Evidence</span><br>";
                    traceHtml += cited.map(name => `<span class='trace-chip'>${escapeHtml(name)}</span>`).join('');
                    traceHtml += "</div>";
                }
                if (actions.length > 0) {
                    traceHtml += "<div style='margin-top:6px'><span class='trace-title'>Next Best Actions</span><br>";
                    traceHtml += actions.map(name => `<span class='trace-chip'>${escapeHtml(name)}</span>`).join('');
                    traceHtml += "</div>";
                }
                traceHtml += "</div>";
                html += traceHtml;
            }

            item.innerHTML = html;
            log.appendChild(item);
            log.scrollTop = log.scrollHeight;
        }

        function closeWelcome() {
            const modal = document.getElementById('welcome-modal');
            if (modal) modal.classList.remove('show');
            sessionStorage.setItem('nemosys_welcome_dismissed', '1');
        }

        async function fetchJson(url, options) {
            const res = await fetch(url, options);
            if (!res.ok) {
                const text = await res.text();
                throw new Error(text || `HTTP ${res.status}`);
            }
            return await res.json();
        }

        async function loadProjects() {
            const projects = await fetchJson('/v1/projects');
            const list = document.getElementById('project-list');
            list.innerHTML = '';
            for (const p of projects) {
                const el = document.createElement('div');
                el.className = 'project-item' + (currentProject && currentProject.id === p.id ? ' active' : '');
                el.innerHTML = `<strong>${p.name}</strong><div class='muted'>${p.id}</div><div class='muted'>${p.description || ''}</div>`;
                el.onclick = () => selectProject(p.id);
                list.appendChild(el);
            }
            if (!currentProject && projects.length > 0) {
                selectProject(projects[0].id);
            }
        }

        async function createProject() {
            const name = document.getElementById('new-project-name').value.trim();
            const description = document.getElementById('new-project-desc').value.trim();
            if (!name) return;
            await fetchJson('/v1/projects', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name, description})
            });
            document.getElementById('new-project-name').value = '';
            document.getElementById('new-project-desc').value = '';
            await loadProjects();
        }

        async function selectProject(projectId) {
            currentProject = await fetchJson(`/v1/projects/${projectId}`);
            document.getElementById('project-title').textContent = currentProject.name;
            document.getElementById('project-meta').textContent = `${currentProject.id} | ${currentProject.output_dir}`;
            await loadProjects();
            await refreshProjectState();
        }

        async function refreshProjectState() {
            if (!currentProject) return;
            const summary = await fetchJson(`/v1/projects/${currentProject.id}/summary`);
            document.getElementById('k-readiness').textContent = summary.readiness || '-';
            document.getElementById('k-critical').textContent = summary.critical || 0;
            document.getElementById('k-warning').textContent = summary.warning || 0;
            document.getElementById('k-passed').textContent = summary.passed || 0;
            document.getElementById('k-executed').textContent = summary.execution?.completed || 0;
            document.getElementById('k-pending').textContent = summary.execution?.blocked_pending_approval || 0;

            const readiness = summary.readiness || 'unknown';
            const critical = summary.critical || 0;
            const warning = summary.warning || 0;
            const executed = summary.execution?.completed || 0;
            const blockedPending = summary.execution?.blocked_pending_approval || 0;
            const blockedRejected = summary.execution?.blocked_rejected || 0;
            const insight =
                `Readiness: ${readiness}\n` +
                `Findings: ${critical} critical, ${warning} warning\n` +
                `Execution: ${executed} completed, ${blockedPending} pending approval, ${blockedRejected} rejected`;
            document.getElementById('status-insight').textContent = insight;

            const artifacts = await fetchJson(`/v1/projects/${currentProject.id}/artifacts`);
            const list = document.getElementById('artifact-list');
            list.innerHTML = '';
            for (const item of artifacts) {
                const row = document.createElement('div');
                row.className = 'artifact-item';
                row.innerHTML = `
                    <div>
                        <a href='/v1/projects/${currentProject.id}/artifacts/${encodeURIComponent(item.name)}' target='_blank'>${item.name}</a>
                    </div>
                    <div class='artifact-meta'>Order ${item.order || 999} | ${item.size} bytes</div>
                    <div class='artifact-blurb'>${item.blurb || 'Generated lifecycle artifact.'}</div>
                `;
                list.appendChild(row);
            }
        }

        async function runFlow() {
            if (!currentProject) return;
            if (runInProgress) return;
            document.getElementById('flow-error').textContent = '';
            runInProgress = true;
            const pyatsInput = document.getElementById('pyats-testbed-path');
            const payload = {
                survey_path: document.getElementById('survey-path').value.trim(),
                bom_path: document.getElementById('bom-path').value.trim() || null,
                workload_path: document.getElementById('workload-path').value.trim() || null,
                pyats_testbed_path: pyatsInput.value.trim() || null,
                context_path: document.getElementById('context-path').value.trim() || null,
                sync_netbox: false,
                execute: document.getElementById('execute-flow').checked,
                auto_approve: document.getElementById('auto-approve').checked,
            };
            if (WINDOWS_PYATS_UNSUPPORTED && payload.pyats_testbed_path) {
                addChat('system', 'NeMoSys detected Windows. pyATS will not run here, so AIDOS will use the CLI health-check fallback instead.');
            }
            if (!payload.survey_path) {
                document.getElementById('flow-error').textContent = 'Survey path is required.';
                runInProgress = false;
                return;
            }

            const runButton = document.querySelector("button.btn-primary[onclick='runFlow()']");
            if (runButton) {
                runButton.disabled = true;
                runButton.textContent = 'Running Flow...';
            }

            resetStages();
            addEvent('Flow request accepted.');
            setStage('intake', 'active');
            addEvent('Reading intake inputs (survey / workload / bom / context).');

            try {
                await new Promise(resolve => setTimeout(resolve, 150));
                setStage('intake', 'done');
                setStage('formalize', 'active');
                addEvent('Building canonical source of truth.');

                await new Promise(resolve => setTimeout(resolve, 120));
                setStage('formalize', 'done');
                setStage('validate', 'active');
                addEvent('Running deterministic validation checks.');

                await new Promise(resolve => setTimeout(resolve, 120));
                setStage('validate', 'done');
                setStage('plan', 'active');
                addEvent('Generating runbook, task graph, and Ansible artifacts.');

                await new Promise(resolve => setTimeout(resolve, 120));
                setStage('plan', 'done');
                setStage('execute', 'active');
                addEvent(payload.execute ? 'Executing tasks with approval rules.' : 'Execution skipped for dry planning run.');

                const flowResult = await fetchJson(`/v1/projects/${currentProject.id}/flow`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });

                const debug = flowResult?.run_debug || {};
                const resolved = debug?.resolved_inputs || {};
                const objectCounts = debug?.netbox?.payload_counts || {};
                const readiness = debug?.readiness || 'unknown';

                addEvent(
                    `Resolved inputs: survey=${resolved.survey_path || '-'} | bom=${resolved.bom_path || '-'} | workload=${resolved.workload_path || '-'} | context=${resolved.context_path || '-'} | network=${resolved.network_layout_path || '-'}`
                );
                addEvent(
                    `Object payload counts: sites=${objectCounts.sites || 0}, racks=${objectCounts.racks || 0}, devices=${objectCounts.devices || 0}, vlans=${objectCounts.vlans || 0}, prefixes=${objectCounts.prefixes || 0}, cables=${objectCounts.cables || 0} | readiness=${readiness}`
                );

                setStage('execute', 'done');
                setStage('verify', 'active');
                addEvent('Running post-execution verification and writing evidence.');
            } catch (err) {
                let message = String(err);
                try {
                    const parsed = JSON.parse(message);
                    if (parsed && parsed.detail) message = parsed.detail;
                } catch (_) {}
                document.getElementById('flow-error').textContent = message;
                addChat('system', `Flow failed: ${message}`);
                const active = document.querySelector('.stage.active');
                if (active) {
                    active.classList.remove('active');
                    active.classList.add('error');
                }
                addEvent(`Flow failed: ${message}`);
                runInProgress = false;
                if (runButton) {
                    runButton.disabled = false;
                    runButton.textContent = 'Run Project Flow';
                }
                return;
            }

            setStage('verify', 'done');
            addEvent('Flow complete. Artifacts and status refreshed.');
            await refreshProjectState();
            addChat('system', 'Flow completed and project artifacts refreshed.');
            runInProgress = false;
            if (runButton) {
                runButton.disabled = false;
                runButton.textContent = 'Run Project Flow';
            }
        }

        function fillDemoPaths() {
            document.getElementById('survey-path').value = 'aidos/examples/site_survey_example.json';
            document.getElementById('workload-path').value = 'aidos/examples/workload_profile_example.yaml';
            document.getElementById('bom-path').value = '';
            document.getElementById('context-path').value = '';
            addChat('system', 'Demo intake paths populated.');
        }

        function fillWesterbyPaths() {
            document.getElementById('survey-path').value = 'aidos/examples/site_survey_westerby_intl.json';
            document.getElementById('workload-path').value = '';
            document.getElementById('bom-path').value = 'aidos/examples/bom_westerby_intl.yaml';
            document.getElementById('context-path').value = 'aidos/examples/context_westerby_intl.json';
            document.getElementById('execute-flow').checked = true;
            addChat('system', 'Westerby International preset loaded (survey/bom/context and execution enabled).');
        }

        function closeWelcome() {
            const modal = document.getElementById('welcome-modal');
            if (modal) modal.classList.remove('show');
            sessionStorage.setItem('nemosys_welcome_dismissed', '1');
        }

        function configurePlatformWarnings() {
            const pyatsWarning = document.getElementById('pyats-warning');
            const pyatsInput = document.getElementById('pyats-testbed-path');
            const welcomePyatsNote = document.getElementById('welcome-pyats-note');
            if (!WINDOWS_PYATS_UNSUPPORTED) {
                if (pyatsWarning) pyatsWarning.classList.add('hidden');
                if (welcomePyatsNote) welcomePyatsNote.textContent = 'pyATS health checks can run here if the package and testbed are installed.';
                return;
            }

            if (pyatsWarning) pyatsWarning.classList.remove('hidden');
            if (pyatsInput) {
                pyatsInput.disabled = true;
                pyatsInput.placeholder = 'pyATS requires Linux or WSL on this system';
                pyatsInput.title = 'pyATS is disabled on Windows. Run AIDOS in Linux or WSL to enable it.';
            }
        }

        async function uploadInputs() {
            if (!currentProject) return;
            const form = new FormData();
            const s = document.getElementById('file-survey').files[0];
            const b = document.getElementById('file-bom').files[0];
            const w = document.getElementById('file-workload').files[0];
            const c = document.getElementById('file-context').files[0];
            if (s) form.append('survey', s);
            if (b) form.append('bom', b);
            if (w) form.append('workload', w);
            if (c) form.append('context', c);
            const res = await fetch(`/v1/projects/${currentProject.id}/intake/upload`, { method: 'POST', body: form });
            if (!res.ok) {
                alert(await res.text());
                return;
            }
            const payload = await res.json();
            const saved = payload.saved || {};
            if (saved.survey_path) document.getElementById('survey-path').value = saved.survey_path;
            if (saved.bom_path) document.getElementById('bom-path').value = saved.bom_path;
            if (saved.workload_path) document.getElementById('workload-path').value = saved.workload_path;
            if (saved.context_path) document.getElementById('context-path').value = saved.context_path;
            addChat('system', 'Files uploaded and intake paths populated.');
        }

        async function clearIntakeState() {
            if (!currentProject) return;
            const ok = window.confirm('Clear saved intake paths and remove uploaded intake files for this project?');
            if (!ok) return;

            const payload = await fetchJson(`/v1/projects/${currentProject.id}/intake/clear`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({remove_uploaded_files: true}),
            });

            document.getElementById('survey-path').value = '';
            document.getElementById('bom-path').value = '';
            document.getElementById('workload-path').value = '';
            document.getElementById('context-path').value = '';
            document.getElementById('flow-error').textContent = '';

            const surveyInput = document.getElementById('file-survey');
            const bomInput = document.getElementById('file-bom');
            const workloadInput = document.getElementById('file-workload');
            const contextInput = document.getElementById('file-context');
            if (surveyInput) surveyInput.value = '';
            if (bomInput) bomInput.value = '';
            if (workloadInput) workloadInput.value = '';
            if (contextInput) contextInput.value = '';

            const removed = payload?.removed_files || 0;
            addChat('system', `Intake state cleared. Removed ${removed} uploaded file(s).`);
            addEvent(`Intake state cleared for project ${currentProject.id}.`);
        }

        async function sendChat() {
            if (!currentProject) return;
            const message = document.getElementById('chat-input').value.trim();
            if (!message) return;
            const sessionId = document.getElementById('chat-session').value.trim() || 'ops-default';
            addChat('you', message);
            document.getElementById('chat-input').value = '';
            const answer = await fetchJson(`/v1/projects/${currentProject.id}/chat`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message, session_id: sessionId}),
            });
            addAssistantAnswer(answer);
        }

        if (sessionStorage.getItem('nemosys_welcome_dismissed') === '1') {
            const modal = document.getElementById('welcome-modal');
            if (modal) modal.classList.remove('show');
        }

        if (sessionStorage.getItem('nemosys_welcome_dismissed') === '1') {
            const modal = document.getElementById('welcome-modal');
            if (modal) modal.classList.remove('show');
        }

        configurePlatformWarnings();
        loadProjects().catch(err => alert(err));
    </script>
</body>
</html>
"""
