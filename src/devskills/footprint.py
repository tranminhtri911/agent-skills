"""Change footprint: how much existing code a change touches (CHG-001..006).

On a complex system the safest change adds new code next to the running logic
and touches existing files only where behaviour must change. This command
measures that from git, read-only:
- new files vs modified/deleted existing files, with added/deleted lines;
- protected paths (`[change] protected_paths`) modified without `--allow-protected`;
- edited existing migrations, deleted source files, large rewrites of existing files;
- files outside the planned scope (`--scope` globs), formatting-only edits;
- existing files untouched for a long time (stable code) that the change modifies.

Findings are review signals; only protected paths and edited migrations fail the gate.
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from devskills.domain_values import is_test_or_generated
from devskills.fsutil import is_lockfile, resolve_repo_root, run_git
from devskills.models import EXEC_COMPLETED, EXEC_NOT_RUN, GATE_BLOCKED, CheckResult, Finding, gate_from_findings
from devskills.output import emit_result, format_findings, severity_summary
from devskills.profile import load_profile

_MIGRATION_PATH = re.compile(r"(^|/)(migrations?|database/migrations|db/migrate|Migrations)/[^/]+$")
_SECONDS_PER_DAY = 86400


@dataclass
class FileChange:
    """One changed path compared with the base revision."""

    path: str
    status: str  # added | modified | deleted
    added: int
    deleted: int
    whitespace_only: bool = False
    days_since_last_change: int | None = None
    is_test_or_generated: bool = False


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`legacy/**`, `app/Services/Pdf/`, `**/*Calculator.php` -> anchored regex; a trailing `/` means the whole folder."""
    pattern = pattern.strip().lstrip("./")
    if pattern.endswith("/"):
        pattern += "**"
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    tokens = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("^" + "".join(tokens.get(part, re.escape(part)) for part in parts) + "$")


def _matches(path: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.match(path) for pattern in patterns)


def _numstat(repo_root, revision: str, *extra: str) -> dict[str, tuple[int, int]] | None:
    output = run_git(repo_root, ["diff", "--numstat", "--no-renames", "-z", "--relative", *extra, revision])
    if output is None:
        return None
    counts: dict[str, tuple[int, int]] = {}
    for record in output.split("\0"):
        fields = record.split("\t")
        if len(fields) == 3 and fields[2]:
            # Binary files print "-" for both counts.
            counts[fields[2]] = (int(fields[0]) if fields[0].isdigit() else 0, int(fields[1]) if fields[1].isdigit() else 0)
    return counts


def base_revision(repo_root, base: str | None) -> str | None:
    """The revision the working tree is compared with: merge-base with `base`, else HEAD."""
    if base:
        merge_base = run_git(repo_root, ["merge-base", base, "HEAD"])
        return merge_base.strip() if merge_base else None
    head = run_git(repo_root, ["rev-parse", "--verify", "HEAD"])
    return head.strip() if head else None


def collect_changes(repo_root, revision: str) -> list[FileChange]:
    """Committed (since `revision`) plus uncommitted and untracked changes, lockfiles excluded."""
    counts = _numstat(repo_root, revision) or {}
    ignoring_whitespace = _numstat(repo_root, revision, "-w", "--ignore-blank-lines") or {}
    statuses: dict[str, str] = {}
    name_status = run_git(repo_root, ["diff", "--name-status", "--no-renames", "-z", "--relative", revision]) or ""
    fields = [field for field in name_status.split("\0") if field]
    for code, path in zip(fields[::2], fields[1::2]):
        statuses[path] = {"A": "added", "D": "deleted"}.get(code[:1], "modified")
    untracked = run_git(repo_root, ["ls-files", "--others", "--exclude-standard", "-z"]) or ""
    for path in (item for item in untracked.split("\0") if item):
        statuses.setdefault(path, "added")
        if path not in counts:
            try:
                with (repo_root / path).open("rb") as handle:
                    counts[path] = (sum(1 for _ in handle), 0)
            except OSError:
                counts[path] = (0, 0)

    now = time.time()
    changes: list[FileChange] = []
    for path, status in sorted(statuses.items()):
        if is_lockfile(path) or path.startswith(".devskills/"):
            continue
        added, deleted = counts.get(path, (0, 0))
        change = FileChange(path, status, added, deleted, is_test_or_generated=is_test_or_generated(path))
        if status == "modified":
            change.whitespace_only = (added + deleted) > 0 and ignoring_whitespace.get(path, (0, 0)) == (0, 0)
        if status != "added":
            last = run_git(repo_root, ["log", "-1", "--format=%ct", revision, "--", path])
            if last and last.strip().isdigit():
                change.days_since_last_change = int((now - int(last.strip())) // _SECONDS_PER_DAY)
        changes.append(change)
    return changes


def footprint_findings(changes: list[FileChange], *, protected: list[str], allowed: list[str], scope: list[str],
                       stable_after_days: int, large_edit_lines: int) -> list[Finding]:
    """Turn the measured changes into review findings (see module docstring)."""
    protected_patterns = [glob_to_regex(item) for item in protected]
    allowed_patterns = [glob_to_regex(item) for item in allowed]
    scope_patterns = [glob_to_regex(item) for item in scope]
    findings: list[Finding] = []
    for change in changes:
        existing = change.status != "added"
        if existing and _matches(change.path, protected_patterns) and not _matches(change.path, allowed_patterns):
            findings.append(Finding("FOOT-PROTECTED", "high", f"protected path {change.status}", change.path,
                                    hint="needs the user's explicit approval (--allow-protected) and characterization tests (CHG-003)"))
        if existing and _MIGRATION_PATH.search(change.path):
            findings.append(Finding("FOOT-MIGRATION-EDITED", "high", f"existing migration {change.status}", change.path,
                                    hint="a migration that may have run anywhere is never edited; add a new one (CHG-006)"))
        if scope_patterns and not change.is_test_or_generated and not _matches(change.path, scope_patterns):
            findings.append(Finding("FOOT-OUT-OF-SCOPE", "medium", f"{change.status} outside the planned scope", change.path,
                                    hint="re-plan or revert this part; unplanned edits hide in reviews (CHG-001)"))
        if change.is_test_or_generated or not existing:
            continue
        if change.status == "deleted":
            findings.append(Finding("FOOT-DELETED", "medium", f"existing file deleted (-{change.deleted})", change.path,
                                    hint="check every caller/string reference; deprecate first for shared code (CHG-004)"))
        elif change.whitespace_only:
            findings.append(Finding("FOOT-FORMAT-ONLY", "low", "only whitespace/formatting changed", change.path,
                                    hint="drop formatting-only edits from a feature diff (CODE-009)"))
        elif change.deleted >= large_edit_lines:
            findings.append(Finding("FOOT-LARGE-EDIT", "medium", f"{change.deleted} existing lines removed or rewritten",
                                    change.path, hint="rewriting running logic: prefer a separate new unit behind a seam/flag (CHG-002)"))
        if change.status == "modified" and (change.days_since_last_change or 0) >= stable_after_days:
            findings.append(Finding("FOOT-STABLE-TOUCHED", "low",
                                    f"stable code modified (unchanged for {change.days_since_last_change} days)", change.path,
                                    hint="pin current behaviour with characterization tests first; keep the edit minimal (CHG-005)"))
    return findings


def summarize(changes: list[FileChange]) -> dict[str, Any]:
    """Line and file totals split into new code, existing code and tests/generated files."""
    def total(items: list[FileChange]) -> dict[str, int]:
        return {"files": len(items), "added": sum(item.added for item in items), "deleted": sum(item.deleted for item in items)}

    source = [item for item in changes if not item.is_test_or_generated]
    return {
        "new_code": total([item for item in source if item.status == "added"]),
        "existing_code": total([item for item in source if item.status != "added"]),
        "tests_and_generated": total([item for item in changes if item.is_test_or_generated]),
    }


def run(args: argparse.Namespace) -> int:
    """CLI handler for `footprint`."""
    repo_root = resolve_repo_root(args.repo)
    profile, _ = load_profile(repo_root)
    settings = profile["change"]
    revision = base_revision(repo_root, args.base)
    if revision is None:
        result = CheckResult(check_id=args.check_id, tool="devskills.footprint", execution_status=EXEC_NOT_RUN,
                             gate_result=GATE_BLOCKED, domain_result="no_git_base",
                             summary="no git history or base revision to compare with")
        return emit_result(args, repo_root, result, ["footprint: blocked — no git history or base revision"])
    changes = collect_changes(repo_root, revision)
    findings = footprint_findings(
        changes, protected=settings["protected_paths"], allowed=args.allow_protected or [], scope=args.scope or [],
        stable_after_days=settings["stable_after_days"], large_edit_lines=settings["large_edit_lines"])
    totals = summarize(changes)
    new, existing = totals["new_code"], totals["existing_code"]
    summary = (f"new code: {new['files']} files +{new['added']}; existing code: {existing['files']} files "
               f"+{existing['added']}/-{existing['deleted']}; {severity_summary(findings)}")
    result = CheckResult(
        check_id=args.check_id, tool="devskills.footprint", execution_status=EXEC_COMPLETED,
        gate_result=gate_from_findings(findings), domain_result=f"existing_lines_removed={existing['deleted']}",
        summary=summary, findings=findings,
        details={"base": args.base or "HEAD", "revision": revision, "totals": totals, "scope": args.scope or [],
                 "protected_paths": settings["protected_paths"], "files": [asdict(change) for change in changes]})
    lines = [f"footprint vs {args.base or 'HEAD'}: {summary}"]
    for change in changes:
        if not change.is_test_or_generated:
            age = f", unchanged {change.days_since_last_change}d before" if change.days_since_last_change is not None else ""
            lines.append(f"  {change.status:<8} +{change.added:<5} -{change.deleted:<5} {change.path}{age}")
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)

