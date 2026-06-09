"""AIDOS CLI with deterministic lifecycle workflow commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import typer
except ModuleNotFoundError:  # pragma: no cover - fallback path
    typer = None

try:
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError:  # pragma: no cover - fallback path
    Console = None
    Table = None

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

console = Console() if Console else None


def _resolve_input_path(path_str: str | None, label: str) -> str | None:
    if path_str is None:
        return None
    candidate = Path(path_str)
    if candidate.exists():
        return str(candidate)

    repo_candidate = REPO_ROOT / candidate
    if repo_candidate.exists():
        return str(repo_candidate)

    basename = candidate.name
    fallback_locations = [
        REPO_ROOT / "aidos" / "examples" / basename,
        REPO_ROOT / "siteops_validator" / "examples" / basename,
    ]
    for fallback in fallback_locations:
        if fallback.exists():
            return str(fallback)

    suggestions = [str(item.relative_to(REPO_ROOT)) for item in fallback_locations if item.parent.exists()]
    suggestion_text = " | ".join(suggestions) if suggestions else "<none>"
    raise FileNotFoundError(
        f"Input file not found for {label}: {path_str}. "
        f"Tried repo-relative and common example paths: {suggestion_text}"
    )


def _render_findings_report(report: dict[str, Any]) -> None:
    if console and Table:
        console.print(f"[bold]AIDOS Validation Report[/bold] - readiness: {report['readiness']}")
        console.print(report.get("summary", ""))

        summary_table = Table(title="Findings Summary")
        summary_table.add_column("Severity")
        summary_table.add_column("Count", justify="right")
        summary_table.add_row("critical", str(len(report.get("critical", []))))
        summary_table.add_row("warning", str(len(report.get("warning", []))))
        summary_table.add_row("passed", str(len(report.get("passed", []))))
        console.print(summary_table)
        return

    print(f"AIDOS Validation Report - readiness: {report.get('readiness', 'unknown')}")
    print(report.get("summary", ""))


def _print_workflow_artifacts(paths: dict[str, str]) -> None:
    if console and Table:
        table = Table(title="AIDOS Lifecycle Artifacts")
        table.add_column("Artifact")
        table.add_column("Path")
        for name, value in paths.items():
            table.add_row(name, value)
        console.print(table)
        return

    print("AIDOS lifecycle artifacts:")
    for name, value in paths.items():
        print(f"- {name}: {value}")


def _run_validate_legacy(
    survey: str,
    bom: str,
    observed: str | None,
    report_out: str | None,
    normalized_out: str | None,
) -> int:
    try:
        from aidos.service import validate_deployment
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", "dependency")
        print(
            "AIDOS dependencies are missing for this interpreter: "
            f"{missing}. Use the workspace venv Python or install deps: "
            "py -3 -m pip install pydantic pandas pyyaml openpyxl rich typer"
        )
        return 1

    try:
        survey_path = _resolve_input_path(survey, "survey")
        bom_path = _resolve_input_path(bom, "bom")
        observed_path = _resolve_input_path(observed, "observed") if observed else None
        output = validate_deployment(survey_path, bom_path, observed_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"AIDOS input error: {exc}")
        return 1

    report = output.report.model_dump(mode="json")
    _render_findings_report(report)

    if normalized_out:
        out = Path(normalized_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"survey": output.normalized_survey, "bom": output.normalized_bom}, indent=2, default=str)
            + "\n",
            encoding="utf-8",
        )

    if report_out:
        out = Path(report_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    return 2 if report["critical"] else 0


def _run_lifecycle(
    *,
    survey: str,
    bom: str | None,
    workload: str | None,
    context: str | None,
    observed: str | None,
    output_dir: str,
    sync_netbox: bool,
    execute: bool,
    auto_approve: bool,
    netbox_base_url: str | None,
    netbox_token: str | None,
    netbox_dry_run: bool | None,
) -> int:
    try:
        from aidos.orchestrator import run_mvp_workflow
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", "dependency")
        print(
            "AIDOS dependencies are missing for this interpreter: "
            f"{missing}. Use the workspace venv Python or install deps: "
            "py -3 -m pip install pydantic pandas pyyaml openpyxl rich typer"
        )
        return 1

    try:
        survey_path = _resolve_input_path(survey, "survey")
        bom_path = _resolve_input_path(bom, "bom") if bom else None
        workload_path = _resolve_input_path(workload, "workload") if workload else None
        context_path = _resolve_input_path(context, "context") if context else None
        observed_path = _resolve_input_path(observed, "observed") if observed else None

        artifacts = run_mvp_workflow(
            survey_path=survey_path,
            bom_path=bom_path,
            workload_path=workload_path,
            context_path=context_path,
            observed_path=observed_path,
            output_dir=output_dir,
            sync_netbox=sync_netbox,
            execute=execute,
            auto_approve=auto_approve,
            netbox_base_url=netbox_base_url,
            netbox_token=netbox_token,
            netbox_dry_run=netbox_dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"AIDOS workflow error: {exc}")
        return 1

    payload = {
        "canonical_sot_json": str(artifacts.canonical_sot_json),
        "netbox_sync_payloads_json": str(artifacts.netbox_sync_payloads_json),
        "validation_report_json": str(artifacts.validation_report_json),
        "missing_data_report_json": str(artifacts.missing_data_report_json),
        "runbook_yaml": str(artifacts.runbook_yaml),
        "ansible_playbook_yml": str(artifacts.ansible_playbook_yml),
        "ansible_bundle_dir": str(artifacts.ansible_bundle_dir),
        "agentic_task_graph_json": str(artifacts.agentic_task_graph_json),
        "evidence_bundle_json": str(artifacts.evidence_bundle_json),
        "observed_state_snapshot_json": str(artifacts.observed_state_snapshot_json),
        "post_execution_verification_report_json": str(artifacts.post_execution_verification_report_json),
    }
    _print_workflow_artifacts(payload)
    return 0


def _run_query(output_dir: str, question: str) -> int:
    try:
        from aidos.orchestrator import query_artifacts
    except ModuleNotFoundError as exc:
        print(f"AIDOS query dependency error: {getattr(exc, 'name', 'unknown')}")
        return 1

    answer = query_artifacts(output_dir, question)
    print(answer.message)
    if answer.cited_artifacts:
        print("\nCited artifacts:")
        for item in answer.cited_artifacts:
            print(f"- {item}")
    if answer.proposed_actions:
        print("\nProposed actions:")
        for action in answer.proposed_actions:
            print(f"- {action}")
    return 0


def _run_chat(output_dir: str, message: str, session_id: str) -> int:
    try:
        from aidos.chat import converse, get_session
    except ModuleNotFoundError as exc:
        print(f"AIDOS chat dependency error: {getattr(exc, 'name', 'unknown')}")
        return 1

    answer = converse(message, output_dir, session_id=session_id)
    print(answer.message)
    if answer.cited_artifacts:
        print("\nCited artifacts:")
        for item in answer.cited_artifacts:
            print(f"- {item}")
    if answer.proposed_actions:
        print("\nProposed actions:")
        for action in answer.proposed_actions:
            print(f"- {action}")
    session = get_session(session_id, output_dir)
    if session:
        turns = len(session.get("turns", []))
        print(f"\nSession {session_id} turns: {turns}")
    return 0


def _run_approval_set(output_dir: str, task_id: str, status: str, reviewer: str | None, reason: str | None) -> int:
    try:
        from aidos.orchestrator import set_task_approval
    except ModuleNotFoundError as exc:
        print(f"AIDOS approval dependency error: {getattr(exc, 'name', 'unknown')}")
        return 1

    record = set_task_approval(output_dir, task_id, status, reviewer, reason)
    print(json.dumps(record, indent=2))
    return 0


def _run_approval_get(output_dir: str, task_id: str | None) -> int:
    try:
        from aidos.orchestrator import get_task_approval, list_task_approvals
    except ModuleNotFoundError as exc:
        print(f"AIDOS approval dependency error: {getattr(exc, 'name', 'unknown')}")
        return 1

    if task_id:
        print(json.dumps(get_task_approval(output_dir, task_id), indent=2))
        return 0

    print(json.dumps(list_task_approvals(output_dir), indent=2))
    return 0


def _build_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIDOS deployment operating system CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest and formalize into canonical SoT artifacts.")
    ingest.add_argument("survey", help="Path to site survey input.")
    ingest.add_argument("--bom", help="Path to BOM input.")
    ingest.add_argument("--workload", help="Path to workload profile for BOM-builder mode.")
    ingest.add_argument("--context", help="Path to project/customer context.")
    ingest.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")

    validate = sub.add_parser("validate", help="Validate deployment intent against site reality.")
    validate.add_argument("survey", help="Path to site survey file.")
    validate.add_argument("bom", nargs="?", help="Path to BOM file.")
    validate.add_argument("--workload", help="Path to workload profile for no-BOM flow.")
    validate.add_argument("--context", help="Path to project/customer context.")
    validate.add_argument("--observed", help="Optional observed-state file.")
    validate.add_argument("--report-out", default="aidos/outputs/aidos_validation_report.json")
    validate.add_argument("--normalized-out", default="aidos/outputs/aidos_normalized_inputs.json")
    validate.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")

    plan = sub.add_parser("plan", help="Generate runbook, ansible skeleton, and task graph.")
    plan.add_argument("survey", help="Path to site survey input.")
    plan.add_argument("--bom", help="Path to BOM input.")
    plan.add_argument("--workload", help="Path to workload profile for no-BOM flow.")
    plan.add_argument("--context", help="Path to project/customer context.")
    plan.add_argument("--observed", help="Optional observed-state file.")
    plan.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")
    plan.add_argument("--sync-netbox", action="store_true")
    plan.add_argument("--netbox-base-url")
    plan.add_argument("--netbox-token")
    plan.add_argument("--netbox-dry-run", action="store_true")

    execute = sub.add_parser("execute", help="Execute planned runbook tasks through Nemosys.")
    execute.add_argument("survey", help="Path to site survey input.")
    execute.add_argument("--bom", help="Path to BOM input.")
    execute.add_argument("--workload", help="Path to workload profile for no-BOM flow.")
    execute.add_argument("--context", help="Path to project/customer context.")
    execute.add_argument("--observed", help="Optional observed-state file.")
    execute.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")
    execute.add_argument("--sync-netbox", action="store_true")
    execute.add_argument("--auto-approve", action="store_true")
    execute.add_argument("--netbox-base-url")
    execute.add_argument("--netbox-token")
    execute.add_argument("--netbox-dry-run", action="store_true")

    query = sub.add_parser("query", help="Query generated artifacts with grounded retrieval.")
    query.add_argument("question", help="Question over AIDOS artifacts.")
    query.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")

    chat = sub.add_parser("chat", help="Conversational artifact-aware assistant mode.")
    chat.add_argument("message", help="Operator message.")
    chat.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")
    chat.add_argument("--session-id", default="default", help="Persistent session id.")

    approve = sub.add_parser("approve", help="Set approval state for a task.")
    approve.add_argument("task_id")
    approve.add_argument("status", choices=["pending", "approved", "rejected"])
    approve.add_argument("--output-dir", default="aidos/outputs")
    approve.add_argument("--reviewer")
    approve.add_argument("--reason")

    approvals = sub.add_parser("approvals", help="Get one or all approval records.")
    approvals.add_argument("--task-id")
    approvals.add_argument("--output-dir", default="aidos/outputs")

    flow = sub.add_parser("flow", help="Run full AIDOS intake-to-verify lifecycle.")
    flow.add_argument("survey", help="Path to site survey input.")
    flow.add_argument("--bom", help="Path to BOM input.")
    flow.add_argument("--workload", help="Path to workload profile for no-BOM flow.")
    flow.add_argument("--context", help="Path to project/customer context.")
    flow.add_argument("--observed", help="Optional observed-state file.")
    flow.add_argument("--output-dir", default="aidos/outputs", help="AIDOS output directory.")
    flow.add_argument("--sync-netbox", action="store_true")
    flow.add_argument("--execute", action="store_true")
    flow.add_argument("--auto-approve", action="store_true")
    flow.add_argument("--netbox-base-url")
    flow.add_argument("--netbox-token")
    flow.add_argument("--netbox-dry-run", action="store_true")

    return parser


def _main_argparse() -> int:
    args = _build_argparse().parse_args()

    if args.command == "ingest":
        if not args.bom and not args.workload:
            print("AIDOS ingest error: provide --bom or --workload.")
            return 1
        return _run_lifecycle(
            survey=args.survey,
            bom=args.bom,
            workload=args.workload,
            context=args.context,
            observed=None,
            output_dir=args.output_dir,
            sync_netbox=False,
            execute=False,
            auto_approve=False,
            netbox_base_url=None,
            netbox_token=None,
            netbox_dry_run=None,
        )

    if args.command == "validate":
        if args.bom:
            return _run_validate_legacy(
                survey=args.survey,
                bom=args.bom,
                observed=args.observed,
                report_out=args.report_out,
                normalized_out=args.normalized_out,
            )
        if not args.workload:
            print("AIDOS validate error: provide BOM positional arg or --workload for no-BOM mode.")
            return 1
        return _run_lifecycle(
            survey=args.survey,
            bom=None,
            workload=args.workload,
            context=args.context,
            observed=args.observed,
            output_dir=args.output_dir,
            sync_netbox=False,
            execute=False,
            auto_approve=False,
            netbox_base_url=None,
            netbox_token=None,
            netbox_dry_run=None,
        )

    if args.command == "plan":
        if not args.bom and not args.workload:
            print("AIDOS plan error: provide --bom or --workload.")
            return 1
        return _run_lifecycle(
            survey=args.survey,
            bom=args.bom,
            workload=args.workload,
            context=args.context,
            observed=args.observed,
            output_dir=args.output_dir,
            sync_netbox=args.sync_netbox,
            execute=False,
            auto_approve=False,
            netbox_base_url=args.netbox_base_url,
            netbox_token=args.netbox_token,
            netbox_dry_run=True if args.netbox_dry_run else None,
        )

    if args.command == "execute":
        if not args.bom and not args.workload:
            print("AIDOS execute error: provide --bom or --workload.")
            return 1
        return _run_lifecycle(
            survey=args.survey,
            bom=args.bom,
            workload=args.workload,
            context=args.context,
            observed=args.observed,
            output_dir=args.output_dir,
            sync_netbox=args.sync_netbox,
            execute=True,
            auto_approve=args.auto_approve,
            netbox_base_url=args.netbox_base_url,
            netbox_token=args.netbox_token,
            netbox_dry_run=True if args.netbox_dry_run else None,
        )

    if args.command == "query":
        return _run_query(args.output_dir, args.question)

    if args.command == "chat":
        return _run_chat(args.output_dir, args.message, args.session_id)

    if args.command == "approve":
        return _run_approval_set(args.output_dir, args.task_id, args.status, args.reviewer, args.reason)

    if args.command == "approvals":
        return _run_approval_get(args.output_dir, args.task_id)

    if args.command == "flow":
        if not args.bom and not args.workload:
            print("AIDOS flow error: provide --bom or --workload.")
            return 1
        return _run_lifecycle(
            survey=args.survey,
            bom=args.bom,
            workload=args.workload,
            context=args.context,
            observed=args.observed,
            output_dir=args.output_dir,
            sync_netbox=args.sync_netbox,
            execute=args.execute,
            auto_approve=args.auto_approve,
            netbox_base_url=args.netbox_base_url,
            netbox_token=args.netbox_token,
            netbox_dry_run=True if args.netbox_dry_run else None,
        )

    return 1


if typer:
    app = typer.Typer(help="AIDOS deployment operating system CLI")

    @app.callback()
    def _root() -> None:
        """AIDOS command group root."""

    @app.command("validate")
    def validate_command(
        survey: str = typer.Argument(...),
        bom: str = typer.Argument(...),
        observed: str | None = typer.Option(None, "--observed"),
        report_out: str | None = typer.Option("aidos/outputs/aidos_validation_report.json", "--report-out"),
        normalized_out: str | None = typer.Option("aidos/outputs/aidos_normalized_inputs.json", "--normalized-out"),
    ) -> None:
        code = _run_validate_legacy(survey, bom, observed, report_out, normalized_out)
        if code:
            raise typer.Exit(code=code)


if __name__ == "__main__":
    raise SystemExit(_main_argparse())
