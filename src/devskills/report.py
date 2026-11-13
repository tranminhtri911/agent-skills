"""Run management, expected-check roster and gate aggregation (plan §26).

The aggregator trusts the roster, not the result files: `required` comes from
the roster written before checks ran, a missing required result is `blocked`,
duplicate results for one check id block the run, and results recorded before
the code changed again are stale (plan §26.2, §26.5, EV20).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from devskills.fsutil import (
    atomic_write_text,
    current_repo_state,
    read_json,
    resolve_repo_root,
    select_target_files,
    sha256_file,
    utc_now_iso,
)
from devskills.models import (
    EXEC_COMPLETED,
    EXIT_BLOCKED,
    EXIT_FAIL,
    EXIT_OK,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_NOT_APPLICABLE,
    GATE_PASS,
    GATE_RESULTS,
    GATE_WARN,
    CheckResult,
    UsageError,
    severity_rank,
)
from devskills.native import planned_ids_for_roster
from devskills.runs import (
    NON_WAIVABLE_CHECKS,
    artifacts_dir,
    build_default_roster,
    load_roster,
    record_check,
    run_dir_checked,
    save_roster,
    start_run,
    tag_changed_paths,
    update_run_risk,
    validate_check_id,
    validate_risk,
)

# --------------------------------------------------------------------------- run / roster commands


def cmd_run_start(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo)
    metadata = start_run(repo_root, args.risk, args.label)
    if args.json:
        print(json.dumps(metadata, indent=2, ensure_ascii=False))
    else:
        print(f"run started: {metadata['run_id']}")
        print(f"  evidence dir: {repo_root / '.devskills' / 'runs' / metadata['run_id']}")
        print("  next: roster init --run RUN_ID --risk R0..R3 (before running checks)")
    return EXIT_OK


def cmd_run_show(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    print(json.dumps(read_json(run_dir / "run.json"), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_roster_init(args: argparse.Namespace) -> int:
    """Derive expected checks from risk and changed files, merging with hand-added entries."""
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    risk = validate_risk(args.risk)
    paths = select_target_files(repo_root, args.paths, "changed", args.base)
    tags = tag_changed_paths(paths)
    native_checks = [] if args.no_native else planned_ids_for_roster(repo_root, paths)
    existing = {entry["check_id"]: entry for entry in (load_roster(run_dir) or [])}
    # Re-initialising keeps hand-added checks and never downgrades a required check.
    for entry in build_default_roster(risk, tags, native_checks):
        previous = existing.get(entry["check_id"])
        if previous is None:
            existing[entry["check_id"]] = entry
        else:
            previous["required"] = previous.get("required", False) or entry["required"]
    merged = list(existing.values())
    save_roster(run_dir, merged, risk)
    update_run_risk(repo_root, args.run, risk)
    if args.json:
        print(json.dumps({"risk": risk, "tags": sorted(tags), "checks": merged}, indent=2, ensure_ascii=False))
    else:
        print(f"roster for {args.run} (risk {risk}, change tags: {', '.join(sorted(tags)) or 'none'}):")
        for entry in merged:
            print(f"  {'REQUIRED' if entry['required'] else 'optional':8} {entry['check_id']:26} {entry['reason']}")
    return EXIT_OK


def cmd_roster_add(args: argparse.Namespace) -> int:
    """Add a check to the roster or make an optional one required (never the reverse)."""
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    check_id = validate_check_id(args.check_id)
    entries = {entry["check_id"]: entry for entry in (load_roster(run_dir) or [])}
    previous = entries.get(check_id)
    required = not args.optional
    if previous and previous.get("required") and not required:
        raise UsageError(f"{check_id} is already required; use `roster waive` with a reason instead of downgrading it")
    entries[check_id] = {"check_id": check_id, "required": required, "reason": args.reason}
    metadata = read_json(run_dir / "run.json")
    save_roster(run_dir, list(entries.values()), metadata.get("risk"))
    print(f"roster: {check_id} {'required' if required else 'optional'} — {args.reason}")
    return EXIT_OK


def cmd_roster_waive(args: argparse.Namespace) -> int:
    """Mark a roster check not applicable with a reason; safety checks cannot be waived."""
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    check_id = validate_check_id(args.check_id)
    if check_id in NON_WAIVABLE_CHECKS:
        raise UsageError(f"{check_id} protects against real damage and cannot be waived")
    if not args.reason.strip():
        raise UsageError("--reason must explain why the check does not apply")
    entries = {entry["check_id"]: entry for entry in (load_roster(run_dir) or [])}
    if check_id not in entries:
        raise UsageError(f"{check_id} is not in the roster")
    entries[check_id] |= {"waived": True, "waiver_reason": args.reason, "waived_at": utc_now_iso()}
    metadata = read_json(run_dir / "run.json")
    save_roster(run_dir, list(entries.values()), metadata.get("risk"))
    print(f"roster: {check_id} marked not_applicable — {args.reason} (shown in the final report)")
    return EXIT_OK


def cmd_roster_show(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    print(json.dumps({"checks": load_roster(run_dir)}, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_attest(args: argparse.Namespace) -> int:
    """Snapshot a document (decision memo, review notes) into the run as evidence for a check."""
    repo_root = resolve_repo_root(args.repo)
    check_id = validate_check_id(args.check_id)
    source = Path(args.file)
    if not source.is_file() or source.stat().st_size == 0:
        raise UsageError(f"artifact must be an existing, non-empty file: {source}")
    destination = artifacts_dir(repo_root, args.run) / f"{check_id}{source.suffix or '.md'}"
    shutil.copyfile(source, destination)
    result = CheckResult(
        check_id=check_id,
        tool="devskills.attest",
        execution_status=EXEC_COMPLETED,
        gate_result=GATE_PASS,
        domain_result="artifact_provided",
        summary=args.note or f"artifact {source.name} provided; content quality is a reviewer decision",
        details={"source": str(source), "sha256": sha256_file(destination)},
        evidence_refs=[str(destination)],
        started_at=utc_now_iso(),
        finished_at=utc_now_iso(),
    )
    path = record_check(repo_root, args.run, result)
    print(f"attested {check_id}: {destination} (sha256 {result.details['sha256'][:12]}…), recorded {path}")
    return EXIT_OK


# --------------------------------------------------------------------------- aggregation


def aggregate(roster: list[dict[str, Any]] | None, results: list[dict[str, Any]], current_digest: str | None,
              risk: str | None) -> dict[str, Any]:
    """Combine roster and recorded results into per-check rows and an overall status."""
    problems: list[str] = []
    if roster is None:
        return {"overall": GATE_BLOCKED, "rows": [], "extra": [], "problems": ["no roster: run `roster init` before checks"]}
    if not roster and risk not in ("R0",):
        problems.append("roster is empty although the risk level requires checks")

    by_id: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_id.setdefault(str(result.get("check_id")), []).append(result)

    rows: list[dict[str, Any]] = []
    roster_ids = set()
    for entry in roster:
        check_id = entry["check_id"]
        roster_ids.add(check_id)
        required = bool(entry.get("required"))
        recorded = by_id.get(check_id, [])
        row: dict[str, Any] = {"check_id": check_id, "required": required, "reason": entry.get("reason", "")}
        if entry.get("waived"):
            row |= {"gate": GATE_NOT_APPLICABLE, "detail": f"waived: {entry.get('waiver_reason')}"}
        elif not recorded:
            row |= {"gate": GATE_BLOCKED if required else GATE_WARN, "detail": "no result recorded (not run)"}
        elif len(recorded) > 1:
            row |= {"gate": GATE_BLOCKED, "detail": f"{len(recorded)} conflicting results for one check id"}
        else:
            result = recorded[0]
            gate = result.get("gate_result")
            detail = result.get("summary", "")
            if gate not in GATE_RESULTS:
                gate, detail = GATE_BLOCKED, f"invalid gate value {gate!r}"
            elif current_digest and (result.get("repo_state") or {}).get("diff_digest") not in (None, current_digest):
                gate, detail = GATE_BLOCKED, "stale: code changed after this check ran; re-run it"
            if not required and gate == GATE_BLOCKED:
                gate = GATE_WARN
            row |= {"gate": gate, "detail": detail, "domain_result": result.get("domain_result"),
                    "findings": len(result.get("findings") or []), "tool": result.get("tool")}
        rows.append(row)

    extra = [{"check_id": check_id, "gate": items[0].get("gate_result"), "detail": "recorded but not in roster"}
             for check_id, items in by_id.items() if check_id not in roster_ids]
    critical_anywhere = any(
        any(finding.get("severity") == "critical" for finding in (result.get("findings") or []))
        for result in results
    )
    required_gates = [row["gate"] for row in rows if row["required"]]
    if any(gate == GATE_FAIL for gate in required_gates) or critical_anywhere:
        overall = GATE_FAIL
    elif problems or any(gate == GATE_BLOCKED for gate in required_gates):
        overall = GATE_BLOCKED
    elif any(row["gate"] in (GATE_WARN, GATE_FAIL, GATE_BLOCKED) for row in rows) or extra:
        overall = GATE_WARN
    else:
        overall = GATE_PASS
    if critical_anywhere:
        problems.append("a critical finding exists in at least one result")
    return {"overall": overall, "rows": rows, "extra": extra, "problems": problems}


def _load_results(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for path in sorted((run_dir / "checks").glob("*.json")):
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            unreadable.append(path.name)
            continue
        data["_file"] = path.name
        results.append(data)
    return results, unreadable


def render_report(metadata: dict[str, Any], aggregation: dict[str, Any], results: list[dict[str, Any]],
                  summary_markdown: str | None) -> str:
    """Render final-report.md: overall gate, agent summary, gate table, findings, limitations, evidence."""
    repository = metadata.get("repository", {})
    lines = [
        f"# Final report — run {metadata['run_id']}",
        "",
        f"- Overall gate: **{aggregation['overall'].upper()}**",
        f"- Risk: {metadata.get('risk') or 'not set'}"
        + (f" (suggested {metadata['suggested_risk']['level']})" if metadata.get("suggested_risk") else ""),
        f"- Repository: `{repository.get('root')}` branch `{repository.get('branch')}` head `{(repository.get('head') or '')[:12]}`",
        f"- Generated: {utc_now_iso()} by devskills {metadata.get('runtime', {}).get('devskills')}",
        "",
    ]
    if summary_markdown:
        lines += [summary_markdown.strip(), ""]
    else:
        lines += ["## What changed and why", "", "_Agent must write this section (`report --summary-file`)._", ""]
    lines += ["## Gates", "", "| Check | Required | Gate | Detail |", "| --- | --- | --- | --- |"]
    for row in aggregation["rows"]:
        detail = str(row.get("detail", "")).replace("|", "\\|")[:160]
        lines.append(f"| {row['check_id']} | {'yes' if row['required'] else 'no'} | {row['gate']} | {detail} |")
    for row in aggregation["extra"]:
        lines.append(f"| {row['check_id']} | extra | {row['gate']} | {row['detail']} |")
    if aggregation["problems"]:
        lines += ["", "## Problems", ""] + [f"- {problem}" for problem in aggregation["problems"]]

    findings = [finding | {"check_id": result.get("check_id")} for result in results for finding in (result.get("findings") or [])]
    findings.sort(key=lambda finding: -severity_rank(finding.get("severity", "")))
    if findings:
        lines += ["", "## Top findings", ""]
        for finding in findings[:25]:
            location = f"{finding.get('path')}:{finding.get('line')}" if finding.get("line") else (finding.get("path") or "-")
            lines.append(f"- [{finding.get('severity')}] {finding.get('rule_id')} `{location}` — {finding.get('message')}")
    trace = next((result for result in results if result.get("tool") == "devskills.trace"), None)
    if trace:
        lines += ["", "## Acceptance traceability", "", "| ID | Criterion | Status | Evidence |", "| --- | --- | --- | --- |"]
        for row in (trace.get("details") or {}).get("criteria") or []:
            cells = [str(row.get("id")), str(row.get("text", ""))[:100], str(row.get("status", "")).upper(),
                     "; ".join(row.get("notes") or [])[:200]]
            lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
        lines += [f"- coverage gap: {gap}" for gap in (trace.get("details") or {}).get("coverage_gaps") or []]
    not_verified = [row for row in aggregation["rows"] if row["gate"] in (GATE_BLOCKED, GATE_WARN, GATE_NOT_APPLICABLE)]
    if not_verified:
        lines += ["", "## Not verified / limitations", ""]
        lines += [f"- {row['check_id']}: {row['gate']} — {row.get('detail', '')}" for row in not_verified]
    lines += ["", "## Evidence", "", f"Check records: `.devskills/runs/{metadata['run_id']}/checks/`"]
    for result in results:
        for reference in (result.get("evidence_refs") or [])[:4]:
            lines.append(f"- {result.get('check_id')}: `{reference}`")
    if not summary_markdown:
        lines += ["", "## Residual risks and next actions", "", "_Agent must list remaining risks, owners and next steps._"]
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    """CLI handler for `report`: aggregate results against the roster and write final-report.md."""
    repo_root = resolve_repo_root(args.repo)
    run_dir = run_dir_checked(repo_root, args.run)
    metadata = read_json(run_dir / "run.json")
    roster = load_roster(run_dir)
    results, unreadable = _load_results(run_dir)
    current_digest = current_repo_state(repo_root).get("diff_digest")
    aggregation = aggregate(roster, results, current_digest, metadata.get("risk"))
    if unreadable:
        aggregation["problems"].append(f"unreadable result files: {', '.join(unreadable)}")
        if aggregation["overall"] in (GATE_PASS, GATE_WARN):
            aggregation["overall"] = GATE_BLOCKED
    summary_markdown = Path(args.summary_file).read_text(encoding="utf-8") if args.summary_file else None
    report_text = render_report(metadata, aggregation, results, summary_markdown)
    out_path = Path(args.out) if args.out else run_dir / "final-report.md"
    atomic_write_text(out_path, report_text)
    if args.json:
        print(json.dumps(aggregation | {"report": str(out_path)}, indent=2, ensure_ascii=False))
    else:
        print(f"overall: {aggregation['overall']}  report: {out_path}")
        for row in aggregation["rows"]:
            print(f"  {row['gate']:15} {'REQ' if row['required'] else 'opt'} {row['check_id']:22} {str(row.get('detail', ''))[:90]}")
        for problem in aggregation["problems"]:
            print(f"  problem: {problem}")
    return {GATE_PASS: EXIT_OK, GATE_WARN: EXIT_OK, GATE_FAIL: EXIT_FAIL}.get(aggregation["overall"], EXIT_BLOCKED)
