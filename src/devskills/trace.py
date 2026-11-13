"""Acceptance traceability: every acceptance criterion points at the evidence that proves it.

Input (`acceptance.json`, template in dev-orchestrate/assets/acceptance.json):
    {"criteria": [{"id": "AC-1", "text": "...", "tags": ["idempotency"],
                   "evidence": [{"test": "orders/tests/test_api.py::test_retry_creates_one_order", "check": "tests.unit"},
                                {"artifact": "artifacts/screens/checkout-mobile.png"},
                                {"review": "reviewed with PO on 2026-10-28"}]}]}

Per criterion the result is:
    verified    a named test with an exact passing identity in a completed check's
                parsed report, or a passing non-test check
    weak        only manual review/artifacts, a test without a linked check, a check that only warned,
                or strong evidence next to a linked item that is missing
    failed      a linked check failed, or the linked test is listed as failing
    unverified  no usable evidence: nothing linked, or every linked test/check/artifact is missing or blocked

Coverage warnings compare criterion tags with the change: DB changes want
concurrency/rollback/migration criteria, API changes contract/authz, UI changes
ui-state/a11y, and R3 work failure/money/idempotency.

Preservation/refactor criteria additionally require a pinned separate baseline
run, exact passing tests before/after, unchanged test-source fingerprints and a
fresh current check. These checks validate evidence, not business semantics.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from devskills.fsutil import (
    atomic_write_text, current_repo_state, is_secret_file, is_within, read_json, read_text_limited,
    resolve_repo_root, select_target_files, sha256_file,
)
from devskills.models import (
    EXEC_COMPLETED,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    Finding,
    UsageError,
)
from devskills.output import emit_result, format_findings
from devskills.runs import RISK_LEVELS, artifacts_dir, run_dir_checked, tag_changed_paths

STATUSES = ("verified", "weak", "failed", "unverified")
# Change tag -> criterion tags of which at least one should appear.
COVERAGE_RULES: dict[str, tuple[str, ...]] = {
    "db": ("concurrency", "rollback", "migration"),
    "api": ("contract", "authz"),
    "ui": ("ui-state", "a11y"),
    "R3": ("failure", "money", "idempotency"),
}
_DB_TAGS = {"sql", "migration", "orm_model"}
PRESERVATION_TAGS = frozenset({"preservation", "refactor"})


def _test_exists(repo_root: Path, reference: str) -> tuple[bool, str]:
    """`path::name` (or `path::Class::method`): the file exists and defines the last name."""
    path_part, _, name_part = reference.partition("::")
    path = (repo_root / path_part).resolve()
    if not path_part or not is_within(path, repo_root) or not path.is_file():
        return False, f"test file not found: {path_part}"
    if not name_part:
        return True, "file exists (no test name given)"
    name = name_part.split("::")[-1].split("[")[0]
    text = read_text_limited(path, 2 * 1024 * 1024) or ""
    # Covers def/function names, describe/it/test strings and PHP/C# method names.
    if re.search(rf"\b{re.escape(name)}\b", text) or name in text:
        return True, "test found"
    return False, f"`{name}` not found in {path_part}"


def _load_checks(run_dir: Path) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for path in (run_dir / "checks").glob("*.json"):
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        checks[data.get("check_id") or path.stem] = data
    return checks


def _test_case_evidence(reference: str, check: dict[str, Any], repo_root: Path) -> tuple[str, str]:
    """Match one exact test identity; never infer execution from a check's totals.

    File attributes are relative to the command's working directory. Without
    one, require the full module/class identity derived from the source path.
    Unknown reporter formats and legacy records need a new, identifiable report.
    """
    attempts = (check.get("details") or {}).get("attempts") or []
    if check.get("execution_status") != EXEC_COMPLETED or not attempts:
        return "unverified", "no completed test execution recorded"
    attempt = attempts[-1]
    if attempt.get("exit_code") != 0 or attempt.get("timed_out") or attempt.get("streams_complete") is False:
        return "unverified", "test execution did not complete successfully"
    junit = attempt.get("junit") or {}
    if not junit.get("files") or junit.get("parse_errors") or not junit.get("cases"):
        return "unverified", "no complete parsed report with testcase identities; rerun the check"
    path_part, _, selector = reference.partition("::")
    if not selector:
        return "unverified", "name a specific testcase with path::name (include class and parameter id when applicable)"
    *classes, test_name = selector.split("::")
    expected_path = (repo_root / path_part).resolve()
    module = expected_path.relative_to(repo_root).with_suffix("").as_posix().replace("/", ".")
    class_name = ".".join(classes)
    expected_classname = ".".join([module, *classes])
    cwd = (repo_root / ((check.get("details") or {}).get("cwd") or ".")).resolve()
    matches = []
    for case in junit["cases"]:
        if case.get("name") != test_name:
            continue
        classname = case.get("classname", "").replace("\\", ".").replace("::", ".")
        if case.get("file"):
            case_path = (cwd / case["file"].replace("\\", "/")).resolve()
            if case_path != expected_path:
                continue
            if classname not in (class_name, expected_classname):
                continue
        elif classname != expected_classname:
            continue
        matches.append(case)
    if not matches:
        return "unverified", f"{reference} has no exact testcase identity in the report"
    if any(case.get("outcome") in ("failure", "error") for case in matches):
        return "failed", f"{reference} failed in the report"
    if len(matches) != 1:
        return "unverified", f"{reference} matches multiple testcase records; use an unambiguous identity"
    if matches[0].get("outcome") != "passed":
        return "unverified", f"{reference} was skipped or has no passing outcome"
    return "verified", f"{reference} ran and passed (exact testcase match)"


def evaluate_criterion(criterion: dict[str, Any], repo_root: Path, run_dir: Path,
                       checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Classify one criterion and explain each piece of evidence."""
    notes: list[str] = []
    strong = weak = failed = missing = False
    evidence_items = criterion.get("evidence") or []
    if not evidence_items:
        missing = True
        notes.append("no evidence linked")
    for item in evidence_items:
        test_ref, check_id = item.get("test"), item.get("check")
        check = checks.get(check_id) if check_id else None
        if check_id and check is None:
            missing = True
            notes.append(f"check {check_id} not recorded in this run")
        gate = check.get("gate_result") if check else None
        if test_ref:
            exists, detail = _test_exists(repo_root, test_ref)
            if not exists:
                missing = True
                notes.append(detail)
                continue
            if gate == GATE_FAIL:
                failed = True
                notes.append(f"{check_id} failed")
            elif gate == GATE_PASS:
                status, detail = _test_case_evidence(test_ref, check, repo_root)
                strong |= status == "verified"
                failed |= status == "failed"
                missing |= status == "unverified"
                notes.append(f"{check_id}: {detail}")
            elif gate == GATE_WARN:
                weak = True
                notes.append(f"{check_id} only warned (no parsed test report)")
            elif gate == GATE_BLOCKED:
                missing = True
                notes.append(f"{check_id} blocked")
            elif not check_id:
                weak = True
                notes.append(f"{test_ref} exists but no check that ran it is linked")
            else:
                missing = True
                notes.append(f"{check_id}: no passing execution evidence")
        elif check_id and check is not None:
            if gate == GATE_PASS:
                strong = True
                notes.append(f"{check_id} pass")
            elif gate == GATE_FAIL:
                failed = True
                notes.append(f"{check_id} failed")
            elif gate == GATE_WARN:
                weak = True
                notes.append(f"{check_id} warn")
            else:
                missing = True
                notes.append(f"{check_id} {gate}")
        if item.get("artifact"):
            reference = str(item["artifact"])
            candidates = [(run_dir / reference).resolve(), (repo_root / reference).resolve()]
            if any(is_within(path, repo_root) and path.exists() for path in candidates):
                weak = True
                notes.append(f"artifact {reference}")
            else:
                missing = True
                notes.append(f"artifact not found: {reference}")
        if item.get("review"):
            weak = True
            notes.append(f"manual review: {str(item['review'])[:80]}")
    if failed:
        status = "failed"
    elif strong and not missing:
        status = "verified"
    elif strong or weak:
        # Some claimed evidence is missing or only manual: usable, but not proof.
        status = "weak"
    else:
        status = "unverified"
    if PRESERVATION_TAGS.intersection(criterion.get("tags") or []) or "preservation" in criterion:
        preservation_status, detail = _preservation_evidence(criterion, repo_root, run_dir, checks)
        notes.append(detail)
        if status != "failed" and preservation_status != "verified":
            status = preservation_status
    return {"id": criterion.get("id"), "text": criterion.get("text", ""), "tags": criterion.get("tags") or [],
            "status": status, "notes": notes}


def _preservation_evidence(criterion: dict[str, Any], repo_root: Path, run_dir: Path,
                           checks: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Require the same unchanged tests to pass on an identified earlier baseline.

    This proves only the linked tests and captured test sources. Reviewing the
    legacy call flow, fixture meaning and unchanged business cases stays required.
    """
    baseline = criterion.get("preservation")
    if not isinstance(baseline, dict):
        return "unverified", "preservation requires baseline_run, baseline_check and baseline_state"
    expected = baseline.get("baseline_state")
    if (not isinstance(expected, dict) or set(expected) != {"head", "diff_digest"}
            or not isinstance(expected.get("diff_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected["diff_digest"])
            or (expected["head"] is not None and (
                not isinstance(expected["head"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected["head"])))):
        return "unverified", "baseline_state must pin head (full commit id or null) and diff_digest (SHA-256)"
    baseline_run = baseline.get("baseline_run")
    if not isinstance(baseline_run, str) or baseline_run == run_dir.name:
        return "unverified", "preservation needs a separate baseline run captured before the change"
    try:
        baseline_dir = run_dir_checked(repo_root, baseline_run)
        if baseline_dir.is_symlink() or not is_within(baseline_dir, repo_root):
            return "unverified", "baseline run must remain inside this repository"
        baseline_check = _load_checks(baseline_dir).get(baseline.get("baseline_check"))
    except (UsageError, OSError, ValueError, TypeError):
        return "unverified", "baseline run/check could not be loaded"
    if not baseline_check:
        return "unverified", "baseline check not recorded"
    if baseline_check.get("gate_result") == GATE_FAIL:
        return "failed", "preservation baseline check failed; bugfix regression tests belong in a separate criterion"
    if baseline_check.get("gate_result") != GATE_PASS:
        return "unverified", "baseline check did not pass"
    details = baseline_check.get("details") or {}
    if details.get("source_state") != expected:
        return "unverified", "baseline check does not match the pinned source state"
    baseline_sources = _stable_test_sources(baseline_check)
    if baseline_sources is None:
        return "unverified", "baseline lacks complete, unchanged test-source fingerprints; rerun it"
    linked_tests = [item for item in criterion.get("evidence") or [] if item.get("test")]
    if not linked_tests:
        return "unverified", "preservation requires named tests; checks, reviews and artifacts alone cannot prove it"
    current_state = current_repo_state(repo_root)
    for item in linked_tests:
        reference = item["test"]
        exists, detail = _test_exists(repo_root, reference)
        if not exists:
            return "unverified", detail
        current = checks.get(item.get("check"))
        if not current or current.get("gate_result") != GATE_PASS:
            return "unverified", "preservation needs a passing current check for every linked test"
        if not current_state.get("diff_digest") or current.get("repo_state") != current_state:
            return "unverified", "current check has no matching repository snapshot or is stale; rerun it"
        for label, record in (("baseline", baseline_check), ("current", current)):
            test_status, detail = _test_case_evidence(reference, record, repo_root)
            if test_status != "verified":
                return test_status, f"{label}: {detail}"
        try:
            baseline_end = datetime.fromisoformat(baseline_check["finished_at"])
            current_start = datetime.fromisoformat(current["started_at"])
            if baseline_end.tzinfo is None or current_start.tzinfo is None or baseline_end > current_start:
                return "unverified", "baseline must finish before current execution starts"
        except (KeyError, TypeError, ValueError):
            return "unverified", "missing execution timestamps for baseline/current comparison"
        current_sources = _stable_test_sources(current)
        relative = (repo_root / reference.partition("::")[0]).resolve().relative_to(repo_root).as_posix()
        if not current_sources or relative not in baseline_sources or relative not in current_sources:
            return "unverified", "linked test source was not fingerprinted in both executions"
        # New tests may be added; existing assertions/helpers cannot be removed or
        # changed while claiming that the same baseline suite still proves equivalence.
        if any(current_sources.get(path) != digest for path, digest in baseline_sources.items()):
            return "unverified", "baseline test assertions/helpers changed or were removed"
        for path, digest in current_sources.items():
            source = repo_root / path
            if is_secret_file(path) or not is_within(source, repo_root) or source.is_symlink() or not source.is_file():
                return "unverified", "captured test source is missing or outside the repository"
            try:
                if source.stat().st_size > 2 * 1024 * 1024 or sha256_file(source) != digest:
                    return "unverified", "test source changed after current execution; rerun it"
            except OSError:
                return "unverified", "captured test source cannot be read"
    return "verified", f"same tests passed against pinned baseline {baseline_run} and current code; test sources unchanged"


def _stable_test_sources(check: dict[str, Any]) -> dict[str, str] | None:
    """Reject legacy, incomplete or self-modifying test-source snapshots."""
    details = check.get("details") or {}
    before, after = details.get("test_sources_before"), details.get("test_sources_after")
    if not isinstance(before, dict) or before != after or before.get("complete") is not True:
        return None
    hashes = before.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        return None
    if any(not isinstance(path, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
           for path, digest in hashes.items()):
        return None
    return hashes


def coverage_gaps(rows: list[dict[str, Any]], change_tags: set[str], risk: str | None) -> list[str]:
    """Change areas without any criterion tagged for their typical failure modes."""
    present = {tag for row in rows for tag in row["tags"]}
    areas = set()
    if change_tags & _DB_TAGS:
        areas.add("db")
    if "api" in change_tags or "api_spec" in change_tags:
        areas.add("api")
    if "ui" in change_tags:
        areas.add("ui")
    if risk == "R3":
        areas.add("R3")
    return [f"{area} change: no criterion tagged {' / '.join(COVERAGE_RULES[area])}"
            for area in sorted(areas) if not present & set(COVERAGE_RULES[area])]


def render_matrix(rows: list[dict[str, Any]], gaps: list[str]) -> str:
    lines = ["# Acceptance traceability", "", "| ID | Criterion | Tags | Status | Evidence |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        cells = [str(row["id"]), row["text"][:120], ", ".join(row["tags"]), row["status"].upper(), "; ".join(row["notes"])[:300]]
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    if gaps:
        lines += ["", "## Coverage gaps", ""] + [f"- {gap}" for gap in gaps]
    return "\n".join(lines) + "\n"


def load_acceptance(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    criteria = data.get("criteria") if isinstance(data, dict) else None
    if not isinstance(criteria, list) or not all(isinstance(item, dict) and item.get("id") for item in criteria):
        raise UsageError(f"{path}: expected {{\"criteria\": [{{\"id\": ..., \"text\": ..., \"evidence\": [...]}}]}}")
    ids = [item["id"] for item in criteria]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise UsageError(f"{path}: duplicate criterion ids {', '.join(duplicates)}")
    return criteria


def run(args: argparse.Namespace) -> int:
    """CLI handler for `trace`: evaluate acceptance.json against the run's recorded checks."""
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    criteria = load_acceptance(Path(args.file))
    checks = _load_checks(run_dir)
    checks.pop(args.check_id, None)  # Never count a previous trace record as evidence for itself.
    rows = [evaluate_criterion(criterion, repo_root, run_dir, checks) for criterion in criteria]
    risk = (read_json(run_dir / "run.json").get("risk") or "R1")
    change_tags = tag_changed_paths(select_target_files(repo_root, None, "changed", args.base))
    gaps = coverage_gaps(rows, change_tags, risk)
    counts = {status: sum(row["status"] == status for row in rows) for status in STATUSES}

    findings = [Finding(rule_id=f"TRACE-{row['status'].upper()}", severity="high" if row["status"] == "failed" else "medium",
                        message=f"{row['id']}: {row['text'][:100]} — {'; '.join(row['notes'])[:200]}")
                for row in rows if row["status"] in ("failed", "unverified")]
    findings += [Finding(rule_id="TRACE-WEAK", severity="low", message=f"{row['id']}: only weak evidence ({'; '.join(row['notes'])[:150]})")
                 for row in rows if row["status"] == "weak"]
    findings += [Finding(rule_id="TRACE-COVERAGE", severity="low", message=gap) for gap in gaps]
    if not rows:
        gate = GATE_BLOCKED
    elif counts["failed"]:
        gate = GATE_FAIL
    elif counts["unverified"]:
        gate = GATE_BLOCKED
    elif counts["weak"] or gaps:
        gate = GATE_WARN
    else:
        gate = GATE_PASS
    matrix = render_matrix(rows, gaps)
    matrix_path = artifacts_dir(repo_root, args.run) / "traceability.md"
    atomic_write_text(matrix_path, matrix)
    result = CheckResult(
        check_id=args.check_id, tool="devskills.trace", execution_status=EXEC_COMPLETED, gate_result=gate,
        domain_result=", ".join(f"{count} {status}" for status, count in counts.items() if count) or "no criteria",
        summary=f"{len(rows)} criteria: " + ", ".join(f"{counts[status]} {status}" for status in STATUSES),
        findings=findings, details={"criteria": rows, "coverage_gaps": gaps, "risk": risk,
                                    "risk_index": RISK_LEVELS.index(risk) if risk in RISK_LEVELS else None},
        evidence_refs=[str(matrix_path), str(Path(args.file))])
    lines = [f"trace: {result.summary}", f"  matrix: {matrix_path}", *format_findings(findings, limit=20)]
    return emit_result(args, repo_root, result, lines)
