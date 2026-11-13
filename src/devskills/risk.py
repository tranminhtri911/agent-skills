"""Risk suggestion R0-R3 from changed paths and diff content (plan §6.2).

Risk comes from side effects and blast radius, not from diff size: a one-line
change to a money sign or a tenant filter can be R3. The output is a
suggestion with reasons; the agent confirms it and may only lower it with an
explicit justification.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

from devskills.fsutil import (
    atomic_write_json,
    git_status_entries,
    is_secret_file,
    read_json,
    read_text_limited,
    resolve_repo_root,
    run_git,
    select_target_files,
)
from devskills.runs import RISK_LEVELS, run_dir_checked

R3_SIGNALS: dict[str, re.Pattern[str]] = {
    "money/payment": re.compile(
        r"(?i)\b(payments?|payouts?|charges?|refunds?|invoices?|billing|wallets?|ledgers?|balances?|"
        r"settlements?|stripe|paypal|vnpay|momo|zalopay|checkout|amount_minor|price|currency)\b"),
    "destructive data": re.compile(r"(?i)\b(drop\s+(table|column|database)|truncate|delete\s+from|hard_delete|purge|wipe|bulk_delete)\b"),
    "production/deploy": re.compile(r"(?i)(\bprod(uction)?\b|deploy|terraform|helm|kubernetes|k8s|\.github/workflows)"),
    "permissions": re.compile(r"(?i)\b(permissions?|roles?|rbac|acl|is_admin|superuser|tenant_id|impersonat\w*)\b"),
}
R2_SIGNALS: dict[str, re.Pattern[str]] = {
    "database": re.compile(r"(?i)(\bselect\b.+\bfrom\b|\binsert\s+into\b|\bupdate\b.+\bset\b|transaction|commit|rollback|"
                           r"\bsession\b|migration|alembic|prisma|eloquent|typeorm|sequelize|sqlalchemy|knex)"),
    "api contract": re.compile(r"(?i)(@(app|router)\.(get|post|put|patch|delete)|Route::|@(Get|Post|Put|Patch|Delete)Mapping|"
                               r"router\.(get|post|put|patch|delete)|openapi|swagger|graphql|status_code|HttpStatus)"),
    "auth/session": re.compile(r"(?i)\b(auth\w*|login|logout|jwt|oauth|session|cookie|csrf|cors|password|token)\b"),
    "cache/queue/concurrency": re.compile(r"(?i)\b(redis|cache|queue|kafka|rabbit\w*|celery|sidekiq|bullmq|thread\w*|"
                                          r"asyncio|executor|mutex|lock|semaphore|goroutine)\b"),
    "batch/jobs": re.compile(r"(?i)\b(batch|cron|schedule\w*|backfill|worker|job)\b"),
    "external integration": re.compile(r"(?i)\b(requests\.|httpx|axios|fetch\(|webhook|http\.client|guzzle|resttemplate|webclient)"),
}
DOC_ONLY_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".txt", ".adoc", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})
PATH_R2 = re.compile(r"(?i)(migrations?|alembic|models?|entities|repositor|controllers?|routes?|routers?|api|middleware|"
                     r"auth|config|settings|\.sql$|docker|compose|\.env\.example)")


def _diff_text(repo_root: Path, base: str | None) -> str:
    """Changed lines only (added/removed), bounded to keep the scan fast."""
    pieces = []
    for args in ([["diff", "HEAD", "--unified=0", "--relative"]]
                 + ([["diff", f"{base}...HEAD", "--unified=0", "--relative"]] if base else [])):
        output = run_git(repo_root, args)
        if output:
            pieces.append(output)
    lines = [line[1:] for line in "\n".join(pieces).splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    return "\n".join(lines)[:2_000_000]


def suggest_risk(paths: list[str], diff_text: str, untracked_texts: dict[str, str]) -> tuple[str, list[str]]:
    """Return (risk level, reasons) using path and content signals."""
    if not paths:
        return "R0", ["no changed files detected; confirm the planned scope manually"]
    reasons: list[str] = []
    level = 0
    code_paths = [path for path in paths if PurePosixPath(path).suffix.lower() not in DOC_ONLY_SUFFIXES]
    if not code_paths:
        return "R0", ["only documentation/assets changed"]
    level = 1
    reasons.append(f"{len(code_paths)} code/config file(s) changed")
    content = diff_text + "\n" + "\n".join(untracked_texts.values()) + "\n" + "\n".join(paths)
    for label, pattern in R2_SIGNALS.items():
        match = pattern.search(content)
        if match:
            level = max(level, 2)
            reasons.append(f"R2 signal [{label}]: '{match.group(0)[:40]}'")
    for path in code_paths:
        if PATH_R2.search(path):
            level = max(level, 2)
            reasons.append(f"R2 path: {path}")
            break
    for label, pattern in R3_SIGNALS.items():
        match = pattern.search(content)
        if match:
            level = 3
            reasons.append(f"R3 signal [{label}]: '{match.group(0)[:40]}'")
    return RISK_LEVELS[level], reasons


def _whole_file_texts(repo_root: Path, paths: list[str]) -> dict[str, str]:
    """Contents of files that `git diff` cannot show: untracked files or explicitly planned paths."""
    texts: dict[str, str] = {}
    for path in paths[:200]:
        if is_secret_file(path):
            continue
        text = read_text_limited(repo_root / path, 256 * 1024)
        if text is not None:
            texts[path] = text
    return texts


def run(args: argparse.Namespace) -> int:
    """CLI handler for `risk`: print the suggested level and reasons; store them in run.json with --run."""
    repo_root = resolve_repo_root(args.repo)
    paths = select_target_files(repo_root, args.paths, "changed", args.base)
    if args.paths:
        diff_text = ""
        whole_files = _whole_file_texts(repo_root, paths)
    else:
        diff_text = _diff_text(repo_root, args.base)
        untracked = [entry["path"] for entry in git_status_entries(repo_root) or [] if entry["code"] == "??"]
        whole_files = _whole_file_texts(repo_root, untracked)
    risk, reasons = suggest_risk(paths, diff_text, whole_files)
    if args.run:
        run_dir = run_dir_checked(repo_root, args.run)
        metadata = read_json(run_dir / "run.json")
        metadata["suggested_risk"] = {"level": risk, "reasons": reasons}
        atomic_write_json(run_dir / "run.json", metadata)
    if args.json:
        print(json.dumps({"suggested_risk": risk, "reasons": reasons, "paths": paths}, indent=2, ensure_ascii=False))
    else:
        print(f"suggested risk: {risk}")
        for reason in reasons[:15]:
            print(f"  - {reason}")
        print("Confirm or raise it; lowering it needs an explicit reason in the report.")
    return 0
