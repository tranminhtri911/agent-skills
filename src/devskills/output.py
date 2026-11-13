"""Printing and recording of check results, shared by every command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from devskills.fsutil import atomic_write_json, utc_now_iso
from devskills.models import CheckResult, Finding, count_by_severity, exit_code_for_gate, severity_rank
from devskills.runs import record_check


def format_findings(findings: list[Finding], limit: int = 40) -> list[str]:
    """Human-readable lines, most severe first, capped so output stays scannable."""
    ordered = sorted(findings, key=lambda item: (-severity_rank(item.severity), item.path or "", item.line or 0))
    lines: list[str] = []
    for finding in ordered[:limit]:
        location = f"{finding.path}:{finding.line}" if finding.path and finding.line else (finding.path or "-")
        lines.append(f"  [{finding.severity.upper():8}] {finding.rule_id} {location}")
        lines.append(f"             {finding.message}")
        if finding.hint:
            lines.append(f"             hint: {finding.hint}")
    if len(ordered) > limit:
        lines.append(f"  ... {len(ordered) - limit} more findings (use --json for all)")
    return lines


def severity_summary(findings: list[Finding]) -> str:
    counts = count_by_severity(findings)
    if not counts:
        return "no findings"
    return ", ".join(f"{count} {severity}" for severity, count in counts.items())


def emit_result(args: argparse.Namespace, repo_root: Path, result: CheckResult, human_lines: list[str]) -> int:
    """Print the result (JSON or text), record it in the run when requested, return the exit code."""
    if result.finished_at is None:
        result.finished_at = utc_now_iso()
    recorded_path = None
    run_id = getattr(args, "run", None)
    if run_id:
        recorded_path = record_check(repo_root, run_id, result)
    out_path = getattr(args, "out", None)
    if out_path:
        atomic_write_json(Path(out_path), result.to_dict())
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        lines = list(human_lines)
        lines.append(f"gate: {result.gate_result}  ({result.summary})" if result.summary else f"gate: {result.gate_result}")
        if recorded_path:
            lines.append(f"recorded: {recorded_path}")
        print("\n".join(lines))
    return exit_code_for_gate(result.gate_result)
