from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from siteops.models import CommandCheck, CommandResult


def load_checks(path_str: str) -> list[CommandCheck]:
    path = Path(path_str)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Checks file must be a JSON array.")

    checks: list[CommandCheck] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        checks.append(
            CommandCheck(
                name=str(item.get("name", "unnamed-check")),
                command=str(item.get("command", "")).strip(),
                success_patterns=[str(x) for x in item.get("success_patterns", [])],
                fail_patterns=[str(x) for x in item.get("fail_patterns", [])],
            )
        )
    return checks


def _find_matches(patterns: list[str], text: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            matches.append(pattern)
    return matches


def run_command_checks(checks: list[CommandCheck], timeout_seconds: int = 30) -> list[CommandResult]:
    results: list[CommandResult] = []

    for check in checks:
        if not check.command:
            results.append(
                CommandResult(
                    name=check.name,
                    command=check.command,
                    exit_code=1,
                    status="failed",
                    stderr="Empty command.",
                )
            )
            continue

        completed = subprocess.run(
            check.command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")

        matched_success = _find_matches(check.success_patterns, combined)
        matched_fail = _find_matches(check.fail_patterns, combined)

        status = "passed"
        if completed.returncode != 0:
            status = "failed"
        if check.success_patterns and not matched_success:
            status = "failed"
        if matched_fail:
            status = "failed"

        results.append(
            CommandResult(
                name=check.name,
                command=check.command,
                exit_code=completed.returncode,
                status=status,
                matched_success=matched_success,
                matched_fail=matched_fail,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )

    return results


def command_results_to_dict(results: list[CommandResult]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in results]
