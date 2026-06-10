from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from siteops.commands import command_results_to_dict, load_checks, run_command_checks
from siteops.engine import generate_report, report_to_dict
from siteops.parsers import read_input


def _write_json(path_str: str, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    out_path = Path(path_str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _print_report(report: dict[str, Any]) -> None:
    print("PRE-DEPLOYMENT VALIDATION REPORT")
    print(report.get("summary", ""))
    print("\nCritical issues:")
    for item in report.get("critical", []):
        print(f"- {item['code']}: {item['message']}")
    print("\nWarnings:")
    for item in report.get("warning", []):
        print(f"- {item['code']}: {item['message']}")
    print("\nPassed checks:")
    for item in report.get("passed", []):
        print(f"- {item['code']}: {item['message']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SiteOps Validator MVP CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_survey = sub.add_parser("parse-survey", help="Normalize a site survey file.")
    parse_survey.add_argument("--survey", required=True, help="Path to survey file (json/csv/xlsx)")
    parse_survey.add_argument("--out", required=True, help="Output path for normalized JSON")

    validate = sub.add_parser("validate", help="Validate survey + BOM and produce report.")
    validate.add_argument("--survey", required=True, help="Path to survey file")
    validate.add_argument("--bom", required=True, help="Path to BOM file")
    validate.add_argument("--out", required=True, help="Output path for report JSON")

    run_checks = sub.add_parser("run-checks", help="Run command checks JSON")
    run_checks.add_argument("--checks", required=True, help="Path to checks JSON file")
    run_checks.add_argument("--out", required=True, help="Output path for command results JSON")
    run_checks.add_argument("--timeout", type=int, default=30, help="Timeout per command in seconds")

    full = sub.add_parser("full-run", help="Run validation and command checks in one report")
    full.add_argument("--survey", required=True, help="Path to survey file")
    full.add_argument("--bom", required=True, help="Path to BOM file")
    full.add_argument("--checks", required=False, help="Path to checks JSON file")
    full.add_argument("--out", required=True, help="Output path for merged report JSON")
    full.add_argument("--timeout", type=int, default=30, help="Timeout per command in seconds")

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "parse-survey":
        survey = read_input(args.survey)
        _write_json(args.out, survey)
        print(f"Normalized survey written to {args.out}")
        return 0

    if args.command == "validate":
        survey = read_input(args.survey)
        bom = read_input(args.bom)
        report = report_to_dict(generate_report(survey, bom))
        _write_json(args.out, report)
        _print_report(report)
        print(f"\nValidation report written to {args.out}")
        return 0

    if args.command == "run-checks":
        checks = load_checks(args.checks)
        results = run_command_checks(checks, timeout_seconds=args.timeout)
        payload = command_results_to_dict(results)
        _write_json(args.out, payload)
        print(f"Command report written to {args.out}")
        return 0

    if args.command == "full-run":
        survey = read_input(args.survey)
        bom = read_input(args.bom)
        report = report_to_dict(generate_report(survey, bom))

        command_results: list[dict[str, Any]] = []
        if args.checks:
            checks = load_checks(args.checks)
            command_results = command_results_to_dict(
                run_command_checks(checks, timeout_seconds=args.timeout)
            )

        merged = {
            "validation": report,
            "command_checks": command_results,
            "overall_status": (
                "degraded"
                if report.get("critical") or any(item.get("status") != "passed" for item in command_results)
                else "healthy"
            ),
        }
        _write_json(args.out, merged)
        _print_report(report)
        print(f"\nFull report written to {args.out}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
