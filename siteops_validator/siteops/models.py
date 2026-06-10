from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ValidationFinding:
    severity: str
    code: str
    message: str
    recommendation: str


@dataclass(slots=True)
class ValidationReport:
    critical: list[ValidationFinding] = field(default_factory=list)
    warning: list[ValidationFinding] = field(default_factory=list)
    passed: list[ValidationFinding] = field(default_factory=list)
    deployment_plan: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical": [asdict(item) for item in self.critical],
            "warning": [asdict(item) for item in self.warning],
            "passed": [asdict(item) for item in self.passed],
            "deployment_plan": self.deployment_plan,
            "summary": self.summary,
        }


@dataclass(slots=True)
class CommandCheck:
    name: str
    command: str
    success_patterns: list[str] = field(default_factory=list)
    fail_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommandResult:
    name: str
    command: str
    exit_code: int
    status: str
    matched_success: list[str] = field(default_factory=list)
    matched_fail: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
