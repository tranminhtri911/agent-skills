"""Shared result models and status vocabulary.

Every command returns a CheckResult so that `report` can aggregate results from
different tools without guessing. Three statuses stay separate on purpose
(plan §26.1): execution status (did the tool run?), domain result (what did it
find?) and gate result (what does policy decide?).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from devskills import SCHEMA_VERSION, __version__

# Gate results allowed in any record (plan §4.1).
GATE_PASS = "pass"
GATE_FAIL = "fail"
GATE_WARN = "warn"
GATE_BLOCKED = "blocked"
GATE_NOT_APPLICABLE = "not_applicable"
GATE_RESULTS = frozenset({GATE_PASS, GATE_FAIL, GATE_WARN, GATE_BLOCKED, GATE_NOT_APPLICABLE})

# Execution statuses describe whether the tool actually ran to completion.
EXEC_NOT_RUN = "not_run"
EXEC_COMPLETED = "completed"
EXEC_TIMED_OUT = "timed_out"
EXEC_TOOL_ERROR = "tool_error"
EXEC_CANCELLED = "cancelled"

# Severities ordered from most to least serious.
SEVERITIES = ("critical", "high", "medium", "low", "info")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(reversed(SEVERITIES))}

# CLI exit codes (plan §24.6). Tool-specific exit codes are stored separately.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAIL = 3
EXIT_BLOCKED = 4
EXIT_INTERNAL = 5


class UsageError(Exception):
    """Invalid arguments or configuration; reported with exit code 2."""


def severity_rank(severity: str) -> int:
    """Return a sortable rank (critical is highest); unknown names rank below info."""
    return _SEVERITY_RANK.get(severity, -1)


@dataclass
class Finding:
    """One issue detected by a check, located in a file when possible."""

    rule_id: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    hint: str | None = None
    # Snippet shown to the reader; callers must redact secrets before setting it.
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        known = {name: data.get(name) for name in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class CheckResult:
    """Outcome of one check in the shape the report aggregator expects."""

    check_id: str
    tool: str
    execution_status: str
    gate_result: str
    domain_result: str | None = None
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    # Repository revision + working-tree digest at record time (freshness, plan §26.5).
    repo_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [finding.to_dict() for finding in self.findings]
        data["schema_version"] = SCHEMA_VERSION
        data["devskills_version"] = __version__
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckResult:
        known = {name: data.get(name) for name in cls.__dataclass_fields__ if name in data}
        known["findings"] = [Finding.from_dict(item) for item in data.get("findings") or []]
        return cls(**known)


def gate_from_findings(findings: Iterable[Finding], fail_on: str = "high") -> str:
    """Map findings to a gate: fail at or above `fail_on`, warn below it, pass when empty."""
    findings = list(findings)
    if not findings:
        return GATE_PASS
    threshold = severity_rank(fail_on)
    if any(severity_rank(finding.severity) >= threshold for finding in findings):
        return GATE_FAIL
    return GATE_WARN


def count_by_severity(findings: Iterable[Finding]) -> dict[str, int]:
    """Return {severity: count} for every severity that occurs."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return {name: counts[name] for name in SEVERITIES if name in counts}


def exit_code_for_gate(gate_result: str) -> int:
    """Translate a gate result into the CLI exit code contract."""
    if gate_result in (GATE_PASS, GATE_WARN, GATE_NOT_APPLICABLE):
        return EXIT_OK
    if gate_result == GATE_FAIL:
        return EXIT_FAIL
    if gate_result == GATE_BLOCKED:
        return EXIT_BLOCKED
    return EXIT_INTERNAL
