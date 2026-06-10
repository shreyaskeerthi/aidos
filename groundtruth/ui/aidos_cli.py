"""Typer CLI for AIDOS deterministic infrastructure validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from groundtruth.aidos.service import validate_deployment

app = typer.Typer(help="AIDOS (AI Deployment Operating System) CLI")
console = Console()


def _write_json(path: str | None, payload: dict) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _render_report(report: dict) -> None:
    console.print(f"[bold]AIDOS Validation Report[/bold] - readiness: {report['readiness']}")
    console.print(report["summary"])

    summary_table = Table(title="Findings Summary")
    summary_table.add_column("Severity")
    summary_table.add_column("Count", justify="right")
    summary_table.add_row("critical", str(len(report["critical"])))
    summary_table.add_row("warning", str(len(report["warning"])))
    summary_table.add_row("passed", str(len(report["passed"])))
    console.print(summary_table)

    detail_table = Table(title="Top Findings")
    detail_table.add_column("Severity")
    detail_table.add_column("Code")
    detail_table.add_column("Message")

    for item in report["critical"][:10]:
        detail_table.add_row("critical", item["code"], item["message"])
    for item in report["warning"][:10]:
        detail_table.add_row("warning", item["code"], item["message"])
    if not detail_table.rows:
        for item in report["passed"][:10]:
            detail_table.add_row("passed", item["code"], item["message"])

    console.print(detail_table)


@app.command("validate")
def validate_command(
    survey: str = typer.Argument(..., help="Path to site survey file (xlsx/csv/json/yaml)."),
    bom: str = typer.Argument(..., help="Path to BOM/config file (csv/json/yaml)."),
    observed: str | None = typer.Option(None, "--observed", help="Optional observed-state file."),
    report_out: str | None = typer.Option(
        "groundtruth/outputs/aidos_validation_report.json",
        "--report-out",
        help="Output JSON report path.",
    ),
    normalized_out: str | None = typer.Option(
        "groundtruth/outputs/aidos_normalized_inputs.json",
        "--normalized-out",
        help="Output normalized inputs JSON path.",
    ),
) -> None:
    """Compare EXPECTED vs REALITY and optionally OBSERVED state."""

    output = validate_deployment(survey, bom, observed)
    report = output.report.model_dump(mode="json")

    _render_report(report)
    _write_json(
        normalized_out,
        {
            "survey": output.normalized_survey,
            "bom": output.normalized_bom,
        },
    )
    _write_json(report_out, report)

    if report["critical"]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
