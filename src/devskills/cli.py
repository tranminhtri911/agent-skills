"""Command-line entry point for the devskills runtime.

Each subcommand lives in its own module and is imported lazily, so frequently
called commands such as the `guard` hook start fast.

Exit codes (plan §24.6): 0 gates passed, 2 usage/config error, 3 check failed,
4 blocked or missing capability, 5 internal runner error. Exit codes of the
wrapped tools (pytest, scanners) are stored in the records, never overwritten.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
from collections.abc import Sequence

from devskills import __version__
from devskills.models import EXIT_INTERNAL, EXIT_USAGE, SEVERITIES, UsageError


def _add_common(parser: argparse.ArgumentParser, *, record_check_id: str | None = None) -> None:
    """Options shared by most commands: repository root, JSON output, run recording."""
    parser.add_argument("--repo", help="repository root (default: git top-level of the current directory)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    if record_check_id is not None:
        parser.add_argument("--run", metavar="RUN_ID", help="record the result into this run (see `run start`)")
        parser.add_argument("--check-id", default=record_check_id, help=f"check id to record (default: {record_check_id})")
        parser.add_argument("--out", metavar="PATH", help="also write the JSON result to PATH")


def _add_file_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--paths", nargs="+", metavar="PATH", help="explicit files or directories to check")
    parser.add_argument("--all", action="store_true", help="check all repository files instead of changed files")
    parser.add_argument("--base", metavar="REF", help="also include files changed since git REF (e.g. main)")


# Help for options declared without one: by option name, or by "command option" when the meaning differs.
_OPTION_HELP = {
    "--run": "evidence run id (from `run start`)",
    "check_id": "check id in the roster, e.g. tests.integration",
    "--reason": "why; stored with the record",
    "--env-file": "dotenv file of synthetic test values passed to the command (checked by preflight first)",
    "--allow-host": "sandbox host the user approved (never production)",
    "--dotenv-not-loaded": "dotenv file the tests do not load (requires --reason)",
    "--base": "also include files changed since git REF (e.g. main)",
    "--json": "print machine-readable JSON",
    "attest --check-id": "check id this artifact is evidence for, e.g. design.memo",
    "inspect --max-files": "stop listing files after this many (large monorepos)",
    "check-sql --engine": "SQL dialect (default: .devskills.toml, then auto-detect)",
    "check-sql --fk-policy": "foreign-key policy (default: .devskills.toml, then allowed)",
    "check-sql --fail-on": "lowest severity that fails the gate",
    "run-tests --profile": "unit_offline: no network; integration_isolated / performance_isolated: loopback only; "
                           "provider_sandbox: only --allow-host hosts",
    "native-checks --profile": "unit_offline: no network; integration_isolated: loopback only",
    "simulate kind": "simulator to start",
    "simulate --host": "bind address (keep it on loopback)",
    "simulate --webhook-secret": "signing secret for simulated webhooks (test value only)",
    "simulate --quiet": "do not log each request",
    "screenshot --url": "local page to capture, e.g. http://127.0.0.1:5173/orders",
    "screenshot --viewport": "repeatable; presets mobile 390x844, tablet 768x1024, laptop 1280x800, desktop 1440x900 or WIDTHxHEIGHT; default mobile + laptop",
    "screenshot --full-page": "capture the whole scrollable page",
    "screenshot --locale": "browser locale (pinned for reproducible captures)",
    "screenshot --timezone": "browser timezone (pinned for reproducible captures)",
    "screenshot --color-scheme": "prefers-color-scheme to emulate",
    "screenshot --timeout-ms": "navigation and wait timeout in milliseconds",
    "visual-diff --baseline": "accepted baseline PNG",
    "visual-diff --current": "new screenshot PNG",
    "visual-diff --baseline-manifest": "capture manifest of the baseline (detects profile mismatch)",
    "visual-diff --current-manifest": "capture manifest of the current screenshot",
    "accept-baseline --current": "reviewed screenshot to promote",
    "accept-baseline --baseline": "baseline path to write",
    "rate-limit-probe --method": "HTTP method",
    "rate-limit-probe --header": "repeatable request header (synthetic values only)",
    "rate-limit-probe --limit-status": "status code that means 'limited'",
    "knowledge init --title": "title of INDEX.md (default: '<project folder> Knowledge Index')",
}


def _fill_missing_help(parser: argparse.ArgumentParser, command: str = "") -> None:
    """Give every option a help line so `help <command>` is self-explanatory."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                _fill_missing_help(sub, f"{command} {name}".strip())
        elif action.help is None:
            key = (action.option_strings or [action.dest])[0]
            action.help = _OPTION_HELP.get(f"{command} {key}") or _OPTION_HELP.get(key)


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree; handlers are 'module:function' strings imported lazily by main()."""
    parser = argparse.ArgumentParser(
        prog="ds.py",
        description="devskills runtime: evidence-producing checks for the developer skill set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
typical flow for a change (record each check with --run <id>):
  ds.py doctor                                   what this machine can verify
  ds.py run start --label "add order cancel"     new evidence run, prints <id>
  ds.py inspect --feature order cancel --run <id>          context map + project conventions
  ds.py risk --run <id>                          suggested risk level R0-R3
  ds.py roster init --run <id> --risk R2         expected checks for that risk
  ds.py native-checks --execute --run <id>       the stack's own lint/typecheck/build (primary evidence)
  ds.py run-tests --run <id> -- python -m pytest -q --junitxml=reports/junit.xml
  ds.py check-code --run <id> / check-sql / scan-secrets / footprint --base main
  ds.py trace --run <id> --file acceptance.json  acceptance criterion -> evidence
  ds.py report --run <id>                        final report against the roster

ds.py help <command> shows a command's options. Exit codes: 0 pass, 2 usage error,
3 check failed, 4 blocked/missing capability, 5 internal error.""",
    )
    parser.add_argument("--version", action="version", version=f"devskills {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    doctor = commands.add_parser("doctor", help="report available capabilities (python, git, browser, sandbox)")
    _add_common(doctor)
    doctor.set_defaults(handler="devskills.doctor:run")

    run = commands.add_parser("run", help="manage evidence runs")
    run_actions = run.add_subparsers(dest="run_action", metavar="ACTION", required=True)
    run_start = run_actions.add_parser("start", help="create a run directory and capture the starting state")
    _add_common(run_start)
    run_start.add_argument("--risk", help="risk level R0-R3 if already known")
    run_start.add_argument("--label", help="short task label")
    run_start.set_defaults(handler="devskills.report:cmd_run_start")
    run_show = run_actions.add_parser("show", help="print run metadata")
    _add_common(run_show)
    run_show.add_argument("--run", required=True, metavar="RUN_ID")
    run_show.set_defaults(handler="devskills.report:cmd_run_show")

    roster = commands.add_parser("roster", help="expected-check roster of a run")
    roster_actions = roster.add_subparsers(dest="roster_action", metavar="ACTION", required=True)
    roster_init = roster_actions.add_parser("init", help="derive expected checks from risk and changed files")
    _add_common(roster_init)
    roster_init.add_argument("--run", required=True, metavar="RUN_ID")
    roster_init.add_argument("--risk", required=True, help="risk level R0-R3")
    roster_init.add_argument("--base", metavar="REF", help="include files changed since git REF")
    roster_init.add_argument("--paths", nargs="+", metavar="PATH", help="planned files when nothing is changed yet")
    roster_init.add_argument("--no-native", action="store_true",
                             help="do not expect native-checks (only when the stack has no runnable tools; say why in the report)")
    roster_init.set_defaults(handler="devskills.report:cmd_roster_init")
    roster_add = roster_actions.add_parser("add", help="add or tighten an expected check")
    _add_common(roster_add)
    roster_add.add_argument("check_id")
    roster_add.add_argument("--run", required=True, metavar="RUN_ID")
    roster_add.add_argument("--optional", action="store_true", help="expect the check without requiring it")
    roster_add.add_argument("--reason", required=True)
    roster_add.set_defaults(handler="devskills.report:cmd_roster_add")
    roster_waive = roster_actions.add_parser("waive", help="mark an expected check not applicable, with a reason")
    _add_common(roster_waive)
    roster_waive.add_argument("check_id")
    roster_waive.add_argument("--run", required=True, metavar="RUN_ID")
    roster_waive.add_argument("--reason", required=True)
    roster_waive.set_defaults(handler="devskills.report:cmd_roster_waive")
    roster_show = roster_actions.add_parser("show", help="print the roster")
    _add_common(roster_show)
    roster_show.add_argument("--run", required=True, metavar="RUN_ID")
    roster_show.set_defaults(handler="devskills.report:cmd_roster_show")

    attest = commands.add_parser("attest", help="record a document artifact (decision memo, review notes) as evidence")
    _add_common(attest)
    attest.add_argument("--run", required=True, metavar="RUN_ID")
    attest.add_argument("--check-id", required=True)
    attest.add_argument("--file", required=True, help="artifact file to snapshot into the run")
    attest.add_argument("--note", help="what the artifact proves")
    attest.set_defaults(handler="devskills.report:cmd_attest")

    inspect = commands.add_parser("inspect", help="inventory the stack and map a feature's files, symbols, callers and tables")
    _add_common(inspect, record_check_id="context.map")
    inspect.add_argument("--feature", nargs="+", metavar="KEYWORD", help="feature keywords, e.g. order checkout")
    inspect.add_argument("--max-files", type=int, default=20000)
    inspect.add_argument("--markdown", metavar="PATH", help="also write the human summary to PATH")
    inspect.add_argument("--codegraph", choices=["auto", "on", "off"],
                         help="CodeGraph call-graph integration (default: DEVSKILLS_CODEGRAPH, then .devskills.toml, then auto)")
    inspect.set_defaults(handler="devskills.inventory:run")

    style = commands.add_parser("style", help="code-style references for the languages, frameworks and style tools found in the source")
    _add_common(style)
    style.add_argument("--path", metavar="FILE", help="answer for one file instead of the whole repository")
    style.set_defaults(handler="devskills.style_routing:run")

    risk = commands.add_parser("risk", help="suggest a risk level R0-R3 from the changed files and diff")
    _add_common(risk)
    risk.add_argument("--base", metavar="REF")
    risk.add_argument("--paths", nargs="+", metavar="PATH", help="planned files when nothing is changed yet")
    risk.add_argument("--run", metavar="RUN_ID", help="store the suggestion in run.json")
    risk.set_defaults(handler="devskills.risk:run")

    check_code = commands.add_parser("check-code", help="static maintainability/safety checks on source files")
    _add_common(check_code, record_check_id="code.static")
    _add_file_selection(check_code)
    check_code.add_argument("--fail-on", choices=SEVERITIES, help="lowest severity that fails the gate (default from profile: high)")
    check_code.set_defaults(handler="devskills.code_checks:run")

    check_sql = commands.add_parser("check-sql", help="static checks on SQL migrations and ORM foreign keys")
    _add_common(check_sql, record_check_id="db.sql_static")
    _add_file_selection(check_sql)
    check_sql.add_argument("--engine", choices=["auto", "postgresql", "mysql", "sqlite", "sqlserver", "oracle", "generic"])
    check_sql.add_argument("--fk-policy", choices=["discouraged", "forbidden", "allowed"])
    check_sql.add_argument("--fail-on", choices=SEVERITIES)
    check_sql.set_defaults(handler="devskills.sql_checks:run")

    scan_secrets = commands.add_parser("scan-secrets", help="find committed secrets; values are always redacted")
    _add_common(scan_secrets, record_check_id="security.secrets")
    _add_file_selection(scan_secrets)
    scan_secrets.set_defaults(handler="devskills.secrets_scan:run")

    pool_budget = commands.add_parser("pool-budget", help="check DB connection budget at deployment peak")
    _add_common(pool_budget, record_check_id="perf.pool_budget")
    pool_budget.add_argument("--group", action="append", required=True, metavar="NAME:REPLICAS:PROCS:POOL:OVERFLOW",
                             help="process group, e.g. web:3:2:5:1 (repeatable)")
    pool_budget.add_argument("--surge-percent", type=float, default=25.0, help="rolling-deploy surge (default 25)")
    pool_budget.add_argument("--peak", action="append", default=[], metavar="NAME=REPLICAS", help="explicit peak replicas")
    pool_budget.add_argument("--other", type=int, default=0, help="connections used by admin/migration/batch tools")
    pool_budget.add_argument("--reserve", type=int, default=0, help="connections kept free for operations")
    pool_budget.add_argument("--db-max", type=int, required=True, help="database max_connections available to the app")
    pool_budget.set_defaults(handler="devskills.pool_budget:run")

    preflight = commands.add_parser("preflight", help="prove the test environment has no production/live targets")
    _add_common(preflight, record_check_id="env.preflight")
    preflight.add_argument("--env-file", action="append", default=[], metavar="PATH")
    preflight.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                           help="sandbox host approved by the user (never a production host)")
    preflight.add_argument("--dotenv-not-loaded", action="append", default=[], metavar="PATH",
                           help="dotenv file the tests do not load (requires --reason)")
    preflight.add_argument("--reason", help="why the --dotenv-not-loaded files are safe to ignore")
    preflight.set_defaults(handler="devskills.preflight:run")

    run_tests = commands.add_parser("run-tests", help="run a test command with env allowlist, network guard, timeout and report parsing")
    _add_common(run_tests, record_check_id="tests.unit")
    run_tests.add_argument("--profile", default="unit_offline",
                           choices=["unit_offline", "integration_isolated", "provider_sandbox", "performance_isolated"])
    run_tests.add_argument("--junit", action="append", default=[], metavar="PATH_OR_GLOB",
                           help="JUnit XML report(s) produced by the command (strongly recommended)")
    run_tests.add_argument("--capture", action="append", default=[], metavar="PATH",
                           help="hash a fresh test-produced API capture inside the repo (repeatable; paths relative to repo root)")
    run_tests.add_argument("--timeout", type=float, help="seconds before the process tree is killed")
    run_tests.add_argument("--env", action="append", default=[], metavar="NAME[=VALUE]", help="pass an extra variable")
    run_tests.add_argument("--env-file", action="append", default=[], metavar="PATH")
    run_tests.add_argument("--allow-host", action="append", default=[], metavar="HOST")
    run_tests.add_argument("--dotenv-not-loaded", action="append", default=[], metavar="PATH")
    run_tests.add_argument("--reason", help="justification for --dotenv-not-loaded")
    run_tests.add_argument("--retries", type=int, default=0, help="re-run a failing command N times to classify flakiness")
    run_tests.add_argument("--cwd", help="working directory inside the repository")
    run_tests.add_argument("--keep-tz", action="store_true", help="do not force TZ=UTC")
    run_tests.add_argument("command_argv", nargs=argparse.REMAINDER, metavar="-- COMMAND",
                           help="test command after `--`, e.g. -- python -m pytest -q")
    run_tests.set_defaults(handler="devskills.runner:run")

    native = commands.add_parser("native-checks", help="plan or run the stack's own typecheck/lint/build/framework checks")
    native.add_argument("--repo", help="repository root (default: git top-level of the current directory)")
    native.add_argument("--json", action="store_true", help="print machine-readable JSON")
    native.add_argument("--run", metavar="RUN_ID", help="record each result into this run")
    native.add_argument("--execute", action="store_true", help="run the planned checks (default: only print the plan)")
    native.add_argument("--kinds", metavar="K1,K2", help="typecheck,lint,build,framework,migrations,test "
                                                        "(default: all but test; tests go through run-tests)")
    native.add_argument("--only", nargs="+", metavar="CHECK_ID", help="run only these planned check ids")
    native.add_argument("--all-projects", action="store_true", help="every subproject, not only those the change touches")
    native.add_argument("--paths", nargs="+", metavar="PATH", help="treat these paths as the change")
    native.add_argument("--base", metavar="REF", help="also include files changed since git REF")
    native.add_argument("--profile", default="unit_offline", choices=["unit_offline", "integration_isolated"])
    native.add_argument("--timeout", type=float, help="seconds per check before the process tree is killed")
    native.add_argument("--env", action="append", default=[], metavar="NAME[=VALUE]", help="pass an extra variable")
    native.add_argument("--env-file", action="append", default=[], metavar="PATH")
    native.set_defaults(handler="devskills.native:run")

    trace = commands.add_parser("trace", help="link acceptance criteria to tests, checks and artifacts of a run")
    _add_common(trace, record_check_id="trace.acceptance")
    trace.add_argument("--file", required=True, metavar="ACCEPTANCE_JSON",
                       help="criteria with evidence links (template: dev-orchestrate/assets/acceptance.json)")
    trace.add_argument("--base", metavar="REF", help="also include files changed since git REF for coverage hints")
    trace.set_defaults(handler="devskills.trace:run")

    api_diff = commands.add_parser("api-diff", help="find breaking changes between two versions of an OpenAPI spec")
    _add_common(api_diff, record_check_id="api.contract_diff")
    api_diff.add_argument("--spec", required=True, metavar="PATH", help="current spec (JSON; YAML needs PyYAML)")
    api_diff.add_argument("--base-ref", metavar="REF", help="git ref holding the previous spec at the same path")
    api_diff.add_argument("--base-file", metavar="PATH", help="previous spec exported to a file")
    api_diff.set_defaults(handler="devskills.api_contract:run")

    api_examples = commands.add_parser("api-examples", help="check API-011 endpoint sample coverage against OpenAPI (offline)")
    _add_common(api_examples, record_check_id="api.examples")
    api_examples.add_argument("--spec", required=True, metavar="PATH", help="OpenAPI 3.0/3.1 JSON (YAML needs PyYAML); defines all operations in scope")
    api_examples.add_argument("--file", required=True, metavar="PATH", help="structured API-011 sample manifest (JSON; see design-api references)")
    api_examples.set_defaults(handler="devskills.api_examples:run")

    check_infra = commands.add_parser("check-infra", help="least-privilege IAM and private-network checks on Terraform/CloudFormation/IAM JSON")
    _add_common(check_infra, record_check_id="infra.static")
    _add_file_selection(check_infra)
    check_infra.add_argument("--fail-on", choices=SEVERITIES, help="lowest severity that fails the gate (default: high)")
    check_infra.set_defaults(handler="devskills.infra_checks:run")

    footprint = commands.add_parser("footprint", help="measure how much existing code a change touches (read-only git)")
    _add_common(footprint, record_check_id="change.footprint")
    footprint.add_argument("--base", metavar="REF", help="compare with the merge-base of REF (default: HEAD, i.e. uncommitted work)")
    footprint.add_argument("--scope", action="append", metavar="GLOB", help="planned paths; edits elsewhere are flagged (repeatable)")
    footprint.add_argument("--allow-protected", action="append", metavar="GLOB",
                           help="protected paths the user approved for this change (repeatable)")
    footprint.set_defaults(handler="devskills.footprint:run")

    simulate = commands.add_parser("simulate", help="run a local stateful simulator (payment, notifications)")
    simulate.add_argument("kind", choices=["payment"])
    simulate.add_argument("--host", default="127.0.0.1")
    simulate.add_argument("--port", type=int, default=8787, help="0 picks a free port")
    simulate.add_argument("--state-file", help="persist simulator state to survive restarts")
    simulate.add_argument("--webhook-secret", default="whsec_simulator_only")
    simulate.add_argument("--delay-seconds", type=float, default=3.0, help="delay for timeout scenarios")
    simulate.add_argument("--quiet", action="store_true")
    simulate.set_defaults(handler="devskills.simulators.payment:cmd_simulate")

    screenshot = commands.add_parser("screenshot", help="capture deterministic screenshots of a local page with Playwright")
    _add_common(screenshot, record_check_id="ui.screenshot")
    screenshot.add_argument("--url", required=True)
    screenshot.add_argument("--name", help="case name used for file names (default derived from URL path)")
    screenshot.add_argument("--viewport", action="append", default=[], metavar="mobile|tablet|laptop|desktop|WxH")
    screenshot.add_argument("--out-dir", help="output directory (default: run artifacts or .devskills/screenshots)")
    screenshot.add_argument("--full-page", action="store_true")
    screenshot.add_argument("--wait-for", metavar="SELECTOR", help="element that must be visible before capture")
    screenshot.add_argument("--wait-text", metavar="TEXT", help="text that must be visible before capture")
    screenshot.add_argument("--locale", default="en-US")
    screenshot.add_argument("--timezone", default="UTC")
    screenshot.add_argument("--color-scheme", choices=["light", "dark"], default="light")
    screenshot.add_argument("--mask", action="append", default=[], metavar="SELECTOR", help="mask a dynamic element")
    screenshot.add_argument("--allow-host", action="append", default=[], metavar="HOST")
    screenshot.add_argument("--baseline-dir", help="compare against <baseline-dir>/<name>-<viewport>.png")
    screenshot.add_argument("--timeout-ms", type=int, default=30000)
    screenshot.set_defaults(handler="devskills.screenshot:run")

    visual_diff = commands.add_parser("visual-diff", help="compare a screenshot with its baseline")
    _add_common(visual_diff, record_check_id="ui.visual")
    visual_diff.add_argument("--baseline", required=True)
    visual_diff.add_argument("--current", required=True)
    visual_diff.add_argument("--diff-out", help="where to write the diff image")
    visual_diff.add_argument("--pixel-threshold", type=int, help="per-channel delta 0-255 counted as different")
    visual_diff.add_argument("--max-diff-ratio", type=float, help="allowed share of different pixels")
    visual_diff.add_argument("--mask", action="append", default=[], metavar="X,Y,W,H", help="ignore a region")
    visual_diff.add_argument("--baseline-manifest")
    visual_diff.add_argument("--current-manifest")
    visual_diff.set_defaults(handler="devskills.visual:cmd_visual_diff")

    accept = commands.add_parser("accept-baseline", help="promote a reviewed screenshot to baseline (requires approver)")
    _add_common(accept)
    accept.add_argument("--current", required=True)
    accept.add_argument("--baseline", required=True)
    accept.add_argument("--approved-by", required=True, help="person who reviewed the diff")
    accept.add_argument("--reason", required=True)
    accept.set_defaults(handler="devskills.visual:cmd_accept_baseline")

    report = commands.add_parser("report", help="aggregate run evidence against the roster into final-report.md")
    _add_common(report)
    report.add_argument("--run", required=True, metavar="RUN_ID")
    report.add_argument("--summary-file", help="markdown written by the agent: what changed, why, residual risks")
    report.add_argument("--out", help="report path (default: <run>/final-report.md)")
    report.set_defaults(handler="devskills.report:cmd_report")

    rate_limit = commands.add_parser("rate-limit-probe", help="verify that a LOCAL endpoint answers 429 under a small capped burst")
    _add_common(rate_limit, record_check_id="security.rate_limit")
    rate_limit.add_argument("--url", required=True, help="loopback URL only, e.g. http://127.0.0.1:8000/api/login")
    rate_limit.add_argument("--method", default="POST")
    rate_limit.add_argument("--header", action="append", default=[], metavar="'Name: value'")
    rate_limit.add_argument("--body-file", help="request body (synthetic credentials only)")
    rate_limit.add_argument("--requests", type=int, default=30, help="total requests (max 500)")
    rate_limit.add_argument("--concurrency", type=int, default=3, help="parallel requests (max 20)")
    rate_limit.add_argument("--expect-within", type=int, help="the limiter should trigger within this many requests")
    rate_limit.add_argument("--limit-status", type=int, default=429)
    rate_limit.add_argument("--no-stop", action="store_true", help="keep sending after the first limited response")
    rate_limit.set_defaults(handler="devskills.security_probe:cmd_rate_limit_probe")

    knowledge = commands.add_parser("knowledge", help="project knowledge index (.knowledge/INDEX.md): init, build, check")
    knowledge_actions = knowledge.add_subparsers(dest="knowledge_action", metavar="ACTION", required=True)
    knowledge_init = knowledge_actions.add_parser("init", help="create .knowledge/ (build.py, config.json) and build it")
    _add_common(knowledge_init)
    knowledge_init.add_argument("--title")
    knowledge_init.add_argument("--language", choices=["en", "vi", "ja"], default="en", help="language of INDEX.md boilerplate")
    knowledge_init.add_argument("--force", action="store_true", help="reinstall build.py and regenerate config.json")
    knowledge_init.set_defaults(handler="devskills.knowledge:run")
    knowledge_build = knowledge_actions.add_parser("build", help="rebuild mirrors and INDEX.md")
    _add_common(knowledge_build)
    knowledge_build.set_defaults(handler="devskills.knowledge:run")
    knowledge_check = knowledge_actions.add_parser("check", help="read-only freshness check (CURRENT/STALE)")
    _add_common(knowledge_check, record_check_id="docs.knowledge")
    knowledge_check.set_defaults(handler="devskills.knowledge:run")

    evidence = commands.add_parser("evidence", help="E2E/manual test evidence by checklist: init, checklist, report")
    evidence_actions = evidence.add_subparsers(dest="evidence_action", required=True, metavar="ACTION")
    evidence_init = evidence_actions.add_parser("init", help="create <root>/<task>/ and add the evidence root to .gitignore")
    evidence_checklist = evidence_actions.add_parser(
        "checklist", help="validate <task>/checklist.json, write checklist.html (vi/en/ja) and one folder per case")
    evidence_report = evidence_actions.add_parser(
        "report", help="write <task>/report.html: every case OK/NG with reasons and links, then each case's steps and screenshots")
    for action_parser, handler, check_id in (
            (evidence_init, "devskills.evidence:cmd_init", "evidence.init"),
            (evidence_checklist, "devskills.evidence:cmd_checklist", "evidence.checklist"),
            (evidence_report, "devskills.evidence:cmd_report", "e2e.evidence")):
        _add_common(action_parser, record_check_id=check_id)
        action_parser.add_argument("--root", metavar="DIR",
                                   help="evidence root (default: .devskills.toml [evidence].root, an existing "
                                        "evidence/ or deploy/evidence/, else evidence/)")
        action_parser.set_defaults(handler=handler)
    evidence_init.add_argument("--task", required=True, help="ticket or task id, one folder per task, e.g. no63_5")
    evidence_checklist.add_argument("--task", required=True, help="task folder whose checklist.json is rendered")
    evidence_report.add_argument("--task", help="report one task (default: every task under the root)")

    spec = commands.add_parser("spec", help="task specs from require.md: init, build (plan.html, sub_tasks, checklist.html), source")
    spec_actions = spec.add_subparsers(dest="spec_action", required=True, metavar="ACTION")
    spec_init = spec_actions.add_parser("init", help="create <specs>/<task>/ with a require.md template and sub_tasks/")
    spec_build = spec_actions.add_parser(
        "build", help="validate the plan, sub task files and checklist; write plan.html and checklist.html (data embedded)")
    spec_source = spec_actions.add_parser("source", help="print the plan or checklist JSON embedded in the task's page")
    spec_build.add_argument("--plan", metavar="FILE", help="plan JSON written outside the task folder (default: the data in plan.html)")
    spec_build.add_argument("--checklist", metavar="FILE",
                            help="checklist JSON, e2e-evidence schema (default: the data in checklist.html)")
    spec_source.add_argument("--part", choices=["plan", "checklist"], default="plan", help="which page's data to print")
    spec_source.add_argument("--out", metavar="FILE", help="write the JSON to FILE instead of printing it")
    spec_source.add_argument("--repo", help="repository root (default: git top-level of the current directory)")
    spec_source.set_defaults(handler="devskills.spec:cmd_source")
    for action_parser in (spec_init, spec_build, spec_source):
        action_parser.add_argument("--root", metavar="DIR",
                                   help="specs root (default: .devskills.toml [spec].root, an existing specs/ or docs/specs/, "
                                        "else specs/)")
        action_parser.add_argument("--task", required=True, help="ticket or task id, one folder per task, e.g. no63_5")
    for action_parser, handler, check_id in ((spec_init, "devskills.spec:cmd_init", "spec.init"),
                                             (spec_build, "devskills.spec:cmd_build", "spec.plan")):
        _add_common(action_parser, record_check_id=check_id)
        action_parser.set_defaults(handler=handler)

    guard = commands.add_parser("guard", help="PreToolUse hook: deny/ask for dangerous shell commands")
    guard.add_argument("--check", metavar="COMMAND", help="evaluate one command instead of reading hook JSON from stdin")
    guard.add_argument("--mode", choices=["standard", "strict", "ask"], default="standard",
                       help="standard: ask for dangerous work, deny catastrophic; strict: deny all; ask: ask for all")
    guard.add_argument("--lang", choices=["auto", "en", "vi"], default="auto",
                       help="language of prompts; auto follows the user's latest message (env DEVSKILLS_GUARD_LANG overrides auto)")
    guard.set_defaults(handler="devskills.guard:run")

    validate = commands.add_parser("validate-skills", help="validate SKILL.md packages (frontmatter, links, commands)")
    validate.add_argument("paths", nargs="*", help="skills directory or individual skill folders")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler="devskills.skillcheck:run")

    help_command = commands.add_parser("help", help="show this overview, or one command's options: `help check-code`")
    help_command.add_argument("topic", nargs="?", choices=sorted(commands.choices), metavar="COMMAND", help="command to explain")
    help_command.set_defaults(handler="")
    _fill_missing_help(parser)
    return parser


def subcommand_names() -> set[str]:
    """Top-level subcommands, used by validate-skills to catch stale documentation."""
    parser = build_parser()
    for action in parser._actions:  # argparse exposes no public accessor for subparsers.
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, run the selected handler and map errors to exit codes (2 usage, 5 internal)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        if args.topic:
            parser.parse_args([args.topic, "--help"])
        parser.print_help()
        return 0
    module_name, _, function_name = args.handler.partition(":")
    try:
        handler = getattr(importlib.import_module(module_name), function_name)
        return int(handler(args))
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 — last-resort boundary: keep the cause, never report success.
        print(f"internal error: {type(error).__name__}: {error}", file=sys.stderr)
        if os.environ.get("DEVSKILLS_DEBUG"):
            traceback.print_exc()
        return EXIT_INTERNAL
