"""Run directories: one evidence folder per task (plan §26.4).

Layout under `<repo>/.devskills/runs/<run_id>/`:
    run.json        metadata captured at start (revision, digest, risk, versions)
    roster.json     expected checks, written before checks run (plan §26.2)
    checks/*.json   one CheckResult per check id
    artifacts/      context map, decision memo, screenshots, reports
    logs/           bounded, redacted command output
"""

from __future__ import annotations

import platform
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from devskills import SCHEMA_VERSION, __version__
from devskills.fsutil import (
    atomic_write_json,
    current_repo_state,
    git_snapshot,
    read_json,
    run_dir_for,
    utc_now_iso,
)
from devskills.models import CheckResult, UsageError

RISK_LEVELS = ("R0", "R1", "R2", "R3")
_CHECK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Checks that protect against real-world damage; they can never be waived (plan §4.5).
NON_WAIVABLE_CHECKS = frozenset({"security.secrets", "env.preflight"})

# Path tags used to derive the default roster from the changed files.
_TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "docs": re.compile(r"\.(md|mdx|rst|txt|adoc)$", re.IGNORECASE),
    "sql": re.compile(r"\.sql$", re.IGNORECASE),
    "migration": re.compile(r"(^|/)(migrations?|alembic|db/migrate|database/migrations|flyway|liquibase)(/|$)", re.IGNORECASE),
    "orm_model": re.compile(r"(^|/)(models?|entities|entity|schema\.prisma)(/|\.|$)|models?\.py$", re.IGNORECASE),
    "api": re.compile(r"(router|routes|controller|endpoint|handler|api|openapi|swagger|graphql|resolver)", re.IGNORECASE),
    "api_spec": re.compile(r"(^|/)[^/]*(openapi|swagger)[^/]*\.(json|ya?ml)$", re.IGNORECASE),
    "ui": re.compile(r"\.(tsx|jsx|vue|svelte|css|scss|sass|less|html)$|(^|/)(pages|screens|components|views|layouts)(/|$)", re.IGNORECASE),
    "infra": re.compile(r"\.(tf|tfvars|hcl)$|\.tf\.json$|(^|/)(terraform|infra|infrastructure|iac|cloudformation|cdk|pulumi)(/|$)"
                        r"|(^|/)(template|serverless)\.ya?ml$", re.IGNORECASE),
    "tests": re.compile(r"(^|/)(tests?|__tests__|spec|e2e)(/|$)|(_test|\.test|\.spec)\.\w+$|(^|/)test_[^/]+$", re.IGNORECASE),
}
_CODE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".php", ".java", ".kt",
    ".cs", ".go", ".rb", ".rs", ".swift", ".scala", ".c", ".cc", ".cpp", ".h", ".hpp", ".dart", ".sql",
})


def new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def validate_risk(risk: str | None) -> str | None:
    if risk is None:
        return None
    normalized = risk.upper()
    if normalized not in RISK_LEVELS:
        raise UsageError(f"risk must be one of {', '.join(RISK_LEVELS)}")
    return normalized


def validate_check_id(check_id: str) -> str:
    if not _CHECK_ID_PATTERN.match(check_id or ""):
        raise UsageError(f"invalid check id {check_id!r}: use lowercase letters, digits, '.', '_' or '-'")
    return check_id


def start_run(repo_root: Path, risk: str | None, label: str | None) -> dict[str, Any]:
    """Create a run directory and capture the starting state."""
    run_id = new_run_id()
    run_dir = run_dir_for(repo_root, run_id)
    for sub_dir in ("checks", "artifacts", "logs"):
        (run_dir / sub_dir).mkdir(parents=True, exist_ok=True)
    snapshot = git_snapshot(repo_root)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "label": label,
        "risk": validate_risk(risk),
        "created_at": utc_now_iso(),
        "repository": {
            "root": str(repo_root),
            "branch": snapshot.get("branch"),
            "uncommitted_at_start": [entry["path"] for entry in snapshot.get("uncommitted", [])],
            **current_repo_state(repo_root),
        },
        "runtime": {
            "devskills": __version__,
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        },
    }
    atomic_write_json(run_dir / "run.json", metadata)
    return metadata


def run_dir_checked(repo_root: Path, run_id: str) -> Path:
    """Return the run directory, raising UsageError when the run was never started."""
    run_dir = run_dir_for(repo_root, run_id)
    if not (run_dir / "run.json").is_file():
        raise UsageError(f"run {run_id} not found under {run_dir.parent}; start one with `run start`")
    return run_dir


def load_run_metadata(repo_root: Path, run_id: str) -> dict[str, Any]:
    return read_json(run_dir_checked(repo_root, run_id) / "run.json")


def update_run_risk(repo_root: Path, run_id: str, risk: str) -> None:
    run_dir = run_dir_checked(repo_root, run_id)
    metadata = read_json(run_dir / "run.json")
    metadata["risk"] = validate_risk(risk)
    atomic_write_json(run_dir / "run.json", metadata)


def record_check(repo_root: Path, run_id: str, result: CheckResult) -> Path:
    """Store a CheckResult under the run, stamped with the current repository state."""
    run_dir = run_dir_checked(repo_root, run_id)
    validate_check_id(result.check_id)
    result.repo_state = current_repo_state(repo_root)
    record_path = run_dir / "checks" / f"{result.check_id}.json"
    atomic_write_json(record_path, result.to_dict())
    return record_path


def artifacts_dir(repo_root: Path, run_id: str) -> Path:
    path = run_dir_checked(repo_root, run_id) / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir(repo_root: Path, run_id: str) -> Path:
    path = run_dir_checked(repo_root, run_id) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tag_changed_paths(paths: list[str]) -> set[str]:
    """Classify changed paths into coarse tags that decide which checks are expected."""
    tags: set[str] = set()
    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in _CODE_SUFFIXES:
            tags.add("code")
        for tag, pattern in _TAG_PATTERNS.items():
            if pattern.search(path):
                tags.add(tag)
    return tags


def build_default_roster(risk: str, tags: set[str],
                         native_checks: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    """Expected checks for a risk level and change shape (plan §6.2, §26.2).

    The roster is computed before any check runs, so a missing result can be
    detected instead of silently passing (EV20). `native_checks` are the
    (check_id, kind) pairs `native-checks` plans for the touched projects; the
    stack's own tools are the primary evidence, `code.static` only supports them.
    """
    risk_index = RISK_LEVELS.index(risk)
    roster: dict[str, dict[str, Any]] = {}

    def expect(check_id: str, required: bool, reason: str) -> None:
        roster[check_id] = {"check_id": check_id, "required": required, "reason": reason}

    expect("security.secrets", True, "every change is scanned for committed secrets (SEC-005)")
    if "code" in tags:
        expect("code.static", True, "supporting static signals on changed code (CODE/DOC/SEC rules)")
    native_need = {
        "lint": (bool(tags & {"code", "infra"}), "the project's own linter/IaC scanners on the touched project"),
        "typecheck": (risk_index >= 1, "the project's own type checker (R1+)"),
        "framework": (risk_index >= 1, "framework system checks (e.g. Django `manage.py check`)"),
        "build": (risk_index >= 2, "production build compiles (R2+)"),
        "migrations": (bool(tags & {"orm_model", "migration"}), "models and migrations agree (no missing migration)"),
    }
    for check_id, kind in native_checks or []:
        required, reason = native_need.get(kind, (False, "native check"))
        if required:
            expect(check_id, True, reason)
    if risk_index >= 1:
        expect("context.map", True, "G1 evidence: entry points, callers, data and tests were traced")
        expect("tests.unit", True, "behavior change needs focused tests (TEST-001)")
        expect("trace.acceptance", True, "each acceptance criterion links to a test, check or artifact")
        if "code" in tags:
            expect("change.footprint", True, "existing code touched stays minimal and inside the plan (CHG-001..006)")
    if tags & {"sql", "migration", "orm_model"}:
        expect("db.sql_static", True, "schema/query changes need SQL and FK-policy checks")
    if "infra" in tags:
        expect("infra.static", True, "IaC change: least-privilege IAM and private-by-default network checks (INF-001..006)")
    if "api_spec" in tags:
        expect("api.contract_diff", True, "the API spec changed: prove there is no unplanned breaking change")
    if tags & {"api", "api_spec"}:
        expect("api.examples", True, "API-011: endpoint samples cover the supplied contract, schemas, errors and evidence status")
    if risk_index >= 2:
        expect("env.preflight", True, "test environment must be proven safe before running (SAFE-001..010)")
        integration_required = bool(tags & {"sql", "migration", "orm_model", "api"})
        expect("tests.integration", integration_required, "DB/API boundaries need integration tests on isolated engines")
        expect("design.memo", risk_index >= 3, "decision memo with tradeoffs and recovery (plan §8.1)")
    if "ui" in tags:
        expect("ui.screenshot", risk_index >= 1, "presentation changes need render/screenshot evidence (plan §13.3)")
    if risk_index >= 3:
        expect("tests.failure_paths", True, "money/batch/destructive paths need failure and simulator tests (MONEY-007)")
    return list(roster.values())


def load_roster(run_dir: Path) -> list[dict[str, Any]] | None:
    roster_path = run_dir / "roster.json"
    if not roster_path.is_file():
        return None
    return read_json(roster_path).get("checks", [])


def save_roster(run_dir: Path, entries: list[dict[str, Any]], risk: str | None) -> Path:
    roster_path = run_dir / "roster.json"
    atomic_write_json(roster_path, {
        "schema_version": SCHEMA_VERSION,
        "risk": risk,
        "updated_at": utc_now_iso(),
        "checks": entries,
    })
    return roster_path
