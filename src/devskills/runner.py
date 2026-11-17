"""Safe test runner for the test-safely skill (plan §18, §24.5).

What it enforces:
- argv only, never a shell string (RUN-001);
- an environment built from an allowlist, so agent credentials do not leak into
  tests (RUN-004, SAFE-001), plus a preflight that blocks production targets
  before the first process starts (SAFE-002, SAFE-010);
- network isolation: macOS sandbox-exec where available, plus a Python socket
  guard for Python processes everywhere (SAFE-003); the record states which
  enforcement actually applied;
- a timeout with process-group cleanup (RUN-005) and bounded, redacted logs (RUN-006);
- exit code, signal, timeout and parsed report kept separate (RUN-008), so an
  exit code of 0 alone never becomes `pass` (AGENT-006, TEST-010).
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devskills.fsutil import (
    current_repo_state,
    ensure_state_dir,
    is_secret_file,
    is_within,
    list_repo_files,
    resolve_repo_root,
    sha256_file,
    utc_now_iso,
)
from devskills.junit import JUnitSummary, parse_junit_files
from devskills.models import (
    EXEC_COMPLETED,
    EXEC_NOT_RUN,
    EXEC_TIMED_OUT,
    EXEC_TOOL_ERROR,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    UsageError,
)
from devskills.output import emit_result, format_findings
from devskills.preflight import (
    compose_service_names,
    evaluate_environment,
    gather_dotenv_sources,
    normalize_not_loaded,
    parse_dotenv,
)
from devskills.profile import load_profile
from devskills.runs import logs_dir, tag_changed_paths
from devskills.secrets_scan import redact_text

# Variables a test process legitimately needs from the agent's environment.
BASE_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TMPDIR", "TEMP", "TMP",
    "VIRTUAL_ENV", "CONDA_PREFIX", "PYENV_ROOT", "PYENV_VERSION", "NVM_DIR", "NVM_BIN", "VOLTA_HOME",
    "JAVA_HOME", "GOPATH", "GOROOT", "GOCACHE", "GOMODCACHE", "CARGO_HOME", "RUSTUP_HOME", "DOTNET_ROOT",
    "COMPOSER_HOME", "GEM_HOME", "GEM_PATH", "BUNDLE_PATH", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    "PLAYWRIGHT_BROWSERS_PATH", "CI",
    # Windows essentials.
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
})

PROFILE_NETWORK_MODE = {
    "unit_offline": "deny",
    "integration_isolated": "local",
    "performance_isolated": "local",
    "provider_sandbox": "allow-listed",
}

# Deny outbound traffic except loopback and local IPC; inherited by every child process.
SEATBELT_PROFILE = (
    "(version 1)\n"
    "(allow default)\n"
    "(deny network-outbound)\n"
    '(allow network-outbound (remote ip "localhost:*"))\n'
    "(allow network-outbound (remote unix-socket))\n"
)

NETGUARD_DIR = Path(__file__).resolve().parent / "netguard"
PUMP_JOIN_SECONDS = 10.0
TERMINATE_GRACE_SECONDS = 5.0


@dataclass
class AttemptOutcome:
    """Facts about one execution of the test command."""

    attempt: int
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout_log: str
    stderr_log: str
    stdout_bytes: int
    stderr_bytes: int
    truncated: bool
    leftover_processes_terminated: bool
    streams_complete: bool
    junit: JUnitSummary | None
    stale_reports_ignored: list[str] = field(default_factory=list)
    output_tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the attempt (the in-memory output tail is omitted)."""
        return {
            "attempt": self.attempt,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_seconds": round(self.duration_seconds, 3),
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "truncated": self.truncated,
            "leftover_processes_terminated": self.leftover_processes_terminated,
            "streams_complete": self.streams_complete,
            "junit": self.junit.to_dict() if self.junit else None,
            "stale_reports_ignored": self.stale_reports_ignored,
        }


class _StreamPump(threading.Thread):
    """Copy a child stream into a capped, redacted log while keeping a short tail in memory."""

    def __init__(self, stream, log_path: Path, cap_bytes: int):
        super().__init__(daemon=True)
        self.stream = stream
        self.log_path = log_path
        self.cap_bytes = cap_bytes
        self.total_bytes = 0
        self.written_bytes = 0
        self.truncated = False
        self.tail: collections.deque[str] = collections.deque(maxlen=40)

    def run(self) -> None:
        """Thread body: redact each line, write it until the cap, keep counting after the cap."""
        with self.log_path.open("wb") as log_file:
            # Keep reading after the cap so the child never blocks on a full pipe.
            for raw_line in iter(lambda: self.stream.readline(65536), b""):
                self.total_bytes += len(raw_line)
                text = redact_text(raw_line.decode("utf-8", errors="replace"))
                self.tail.append(text.rstrip("\n"))
                encoded = text.encode("utf-8")
                if self.written_bytes + len(encoded) <= self.cap_bytes:
                    log_file.write(encoded)
                    self.written_bytes += len(encoded)
                elif not self.truncated:
                    log_file.write(b"\n[devskills] output truncated: cap reached\n")
                    self.truncated = True
        self.stream.close()


def _signal_group(process_group_id: int, signal_number: int) -> bool:
    try:
        os.killpg(process_group_id, signal_number)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _group_alive(process_group_id: int) -> bool:
    if os.name == "nt":
        return False
    return _signal_group(process_group_id, 0)


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stop the whole process tree of the run, never processes outside it (RUN-005)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        return
    if _signal_group(process.pid, signal.SIGTERM):
        deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
        while time.monotonic() < deadline and _group_alive(process.pid):
            time.sleep(0.1)
    _signal_group(process.pid, signal.SIGKILL)


def build_environment(
    extra_env: list[str], env_files: list[str], repo_root: Path, keep_tz: bool
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (child environment, explicitly added variables) built from the allowlist."""
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in BASE_ENV_ALLOWLIST or key.startswith("LC_")
    }
    added: dict[str, str] = {}
    for file_name in env_files:
        path = (repo_root / file_name) if not Path(file_name).is_absolute() else Path(file_name)
        try:
            added.update(parse_dotenv(path.read_text(encoding="utf-8")))
        except OSError as error:
            raise UsageError(f"cannot read --env-file {file_name}: {error}") from error
    for item in extra_env:
        name, separator, value = item.partition("=")
        if not separator:
            if name not in os.environ:
                raise UsageError(f"--env {name}: variable is not set in the current environment")
            value = os.environ[name]
        added[name] = value
    environment.update(added)
    if not keep_tz and "TZ" not in added:
        # Deterministic time zone unless the test explicitly needs another one (TEST-005).
        environment["TZ"] = "UTC"
    environment.setdefault("NO_COLOR", "1")
    return environment, added


def plan_network_enforcement(network_mode: str, allowed_hosts: set[str]) -> tuple[list[str], str]:
    """Choose the strongest available enforcement and describe it truthfully."""
    if network_mode == "allow":
        return [], "none"
    sandbox_exec = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    # Seatbelt can express loopback only, so allowed remote hosts fall back to the Python guard.
    if sandbox_exec and not allowed_hosts:
        return [sandbox_exec, "-p", SEATBELT_PROFILE], "os_sandbox_macos+python_socket_guard"
    return [], "python_socket_guard_only(partial: native drivers bypass it)"


def classify_attempt(attempt: AttemptOutcome, junit_requested: bool, argv: list[str],
                     exit_code_is_evidence: bool = False) -> tuple[str, str, str, str]:
    """Return (execution_status, domain_result, gate_result, reason) for one attempt."""
    if attempt.timed_out:
        # devskills:ignore GEN-HARDCODED-DOMAIN-VALUE domain_result has its own vocabulary that happens to share this word
        return EXEC_TIMED_OUT, "timed_out", GATE_BLOCKED, "timed out; process tree terminated"
    if attempt.exit_code is not None and attempt.exit_code < 0:
        return EXEC_COMPLETED, "killed_by_signal", GATE_BLOCKED, f"terminated by signal {-attempt.exit_code}"
    junit = attempt.junit
    if junit_requested:
        if junit is None or not junit.files:
            if attempt.exit_code == 0:
                return EXEC_COMPLETED, "no_report", GATE_BLOCKED, "exit 0 but the required JUnit report was not produced"
            return EXEC_COMPLETED, "failed_no_report", GATE_FAIL, f"exit {attempt.exit_code} and no JUnit report"
        if junit.parse_errors:
            return EXEC_COMPLETED, "report_unparseable", GATE_BLOCKED, "; ".join(junit.parse_errors)[:300]
        if junit.tests == 0:
            return EXEC_COMPLETED, "no_tests", GATE_BLOCKED, "no tests were collected"
        if junit.failures or junit.errors:
            return EXEC_COMPLETED, "failed", GATE_FAIL, f"{junit.failures} failures, {junit.errors} errors"
        if junit.skipped == junit.tests:
            return EXEC_COMPLETED, "all_skipped", GATE_BLOCKED, "every test was skipped"
        if attempt.exit_code != 0:
            return EXEC_COMPLETED, "nonzero_exit", GATE_FAIL, (
                f"tests passed but exit code was {attempt.exit_code} (coverage threshold, teardown or tool error)"
            )
        return EXEC_COMPLETED, "passed", GATE_PASS, f"{junit.passed} passed, {junit.skipped} skipped"
    uses_pytest = "pytest" in argv or any(part.endswith("pytest") for part in argv[:3])
    if uses_pytest and attempt.exit_code == 5:
        return EXEC_COMPLETED, "no_tests", GATE_BLOCKED, "pytest collected no tests (exit 5)"
    if attempt.exit_code == 0 and exit_code_is_evidence:
        return EXEC_COMPLETED, "passed", GATE_PASS, "exit 0 (the tool's own success contract)"
    if attempt.exit_code == 0:
        return EXEC_COMPLETED, "exit_zero_unparsed", GATE_WARN, (
            "exit 0 without a parsed report: test counts are unverified (pass --junit)"
        )
    return EXEC_COMPLETED, "failed", GATE_FAIL, f"exit code {attempt.exit_code}"


def decide_outcome(attempts: list[AttemptOutcome], junit_requested: bool, argv: list[str],
                   exit_code_is_evidence: bool = False) -> tuple[str, str, str, str]:
    """Combine attempts; a pass that needed retries is `flaky`, never a clean pass (TEST-007)."""
    final = classify_attempt(attempts[-1], junit_requested, argv, exit_code_is_evidence)
    if len(attempts) > 1 and final[2] in (GATE_PASS, GATE_WARN):
        first_reason = classify_attempt(attempts[0], junit_requested, argv, exit_code_is_evidence)[3]
        return final[0], "flaky", GATE_BLOCKED, (
            f"passed only after {len(attempts) - 1} retr{'y' if len(attempts) == 2 else 'ies'}; "
            f"first failure kept: {first_reason}"
        )
    return final


def _collect_reports(patterns: list[str], base_dirs: list[Path], allowed_roots: list[Path], not_before: float) -> tuple[list[Path], list[str]]:
    """Find report files written by this attempt; older files are stale and ignored."""
    fresh: list[Path] = []
    stale: list[str] = []
    for pattern in patterns:
        candidates: list[str] = []
        if Path(pattern).is_absolute():
            candidates = glob.glob(pattern, recursive=True)
        else:
            for base_dir in base_dirs:
                candidates.extend(glob.glob(str(base_dir / pattern), recursive=True))
        for candidate in dict.fromkeys(candidates):
            path = Path(candidate)
            if not path.is_file() or not any(is_within(path, root) for root in allowed_roots):
                continue
            # A 2-second margin covers filesystems with coarse timestamps.
            if path.stat().st_mtime + 2 < not_before:
                stale.append(str(path))
            else:
                fresh.append(path)
    return fresh, stale


def execute_once(
    attempt_number: int,
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
    cap_bytes: int,
    log_directory: Path,
    junit_patterns: list[str],
    allowed_roots: list[Path],
) -> AttemptOutcome:
    """Run the command once with process-group isolation, bounded logs and a timeout."""
    stdout_log = log_directory / f"attempt{attempt_number}.stdout.log"
    stderr_log = log_directory / f"attempt{attempt_number}.stderr.log"
    started_wall = time.time()
    started = time.monotonic()
    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **popen_kwargs)
    stdout_pump = _StreamPump(process.stdout, stdout_log, cap_bytes)
    stderr_pump = _StreamPump(process.stderr, stderr_log, cap_bytes)
    stdout_pump.start()
    stderr_pump.start()

    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        exit_code = process.wait()
    leftover_terminated = False
    if not timed_out and _group_alive(process.pid):
        # Servers or workers left behind by the tests would leak resources between runs.
        leftover_terminated = True
        _terminate_tree(process)
    stdout_pump.join(PUMP_JOIN_SECONDS)
    stderr_pump.join(PUMP_JOIN_SECONDS)
    duration = time.monotonic() - started

    junit_summary = None
    stale_reports: list[str] = []
    if junit_patterns:
        report_paths, stale_reports = _collect_reports(junit_patterns, [cwd], allowed_roots, started_wall)
        junit_summary = parse_junit_files(report_paths)
    return AttemptOutcome(
        attempt=attempt_number,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_seconds=duration,
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        stdout_bytes=stdout_pump.total_bytes,
        stderr_bytes=stderr_pump.total_bytes,
        truncated=stdout_pump.truncated or stderr_pump.truncated,
        leftover_processes_terminated=leftover_terminated,
        streams_complete=not (stdout_pump.is_alive() or stderr_pump.is_alive()),
        junit=junit_summary,
        stale_reports_ignored=stale_reports,
        output_tail=list(stderr_pump.tail)[-15:] + list(stdout_pump.tail)[-15:],
    )


def _resolve_executable(argv: list[str], environment: dict[str, str], cwd: Path) -> str | None:
    program = argv[0]
    if os.sep in program or (os.altsep and os.altsep in program):
        candidate = (cwd / program) if not Path(program).is_absolute() else Path(program)
        return str(candidate) if candidate.exists() else None
    return shutil.which(program, path=environment.get("PATH"))


def test_source_snapshot(repo_root: Path) -> dict[str, Any]:
    """Hash conventional test/helper source files without reading secrets or following links.

    These hashes detect changed assertions between baseline/current executions;
    they do not attest to external fixtures, dependencies or test semantics.
    """
    paths, truncated = list_repo_files(repo_root)
    hashes: dict[str, str] = {}
    complete = not truncated
    for relative in paths:
        if not {"tests", "code"} <= tag_changed_paths([relative]) or is_secret_file(relative):
            continue
        path = repo_root / relative
        if path.is_symlink() or not is_within(path, repo_root):
            complete = False
            continue
        if not path.exists():
            continue  # Git can list deleted tracked files.
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                complete = False
                continue
            hashes[relative] = sha256_file(path)
        except OSError:
            complete = False
    return {"complete": complete, "hashes": hashes}


def _capture_records(repo_root: Path, paths: list[str], not_before: float) -> tuple[dict[str, str], list[str]]:
    """Fingerprint only fresh, bounded test outputs; never follow links or read secrets."""
    records: dict[str, str] = {}
    errors: list[str] = []
    for relative in paths:
        path = repo_root / relative
        try:
            if (path.is_symlink() or not is_within(path, repo_root) or not path.is_file()
                    or path.stat().st_size > 2 * 1024 * 1024 or path.stat().st_mtime < not_before
                    or path.stat().st_mtime > time.time() + 1):
                errors.append(relative)
                continue
            records[relative] = sha256_file(path)
        except OSError:
            errors.append(relative)
    return records, errors


def execute_check(
    repo_root: Path,
    argv: list[str],
    *,
    check_id: str,
    profile_name: str = "unit_offline",
    junit_patterns: list[str] | None = None,
    timeout: float | None = None,
    extra_env: list[str] | None = None,
    env_files: list[str] | None = None,
    allowed_hosts: set[str] | None = None,
    cwd: Path | None = None,
    retries: int = 0,
    keep_tz: bool = False,
    not_loaded: set[str] | None = None,
    run_id: str | None = None,
    exit_code_is_evidence: bool = False,
    capture_paths: list[str] | None = None,
) -> tuple[CheckResult, list[str]]:
    """Run one command through every safety layer and return (result, human lines).

    Shared by `run-tests` and `native-checks`. With `exit_code_is_evidence`, exit 0 is a
    pass on its own (typecheck/lint/build contract); test commands keep needing a report.
    """
    profile, profile_warnings = load_profile(repo_root)
    started_at = utc_now_iso()
    junit_patterns = list(junit_patterns or [])
    allowed_hosts = {host.lower() for host in (allowed_hosts or set())}
    cwd = (cwd or repo_root).resolve()
    if not is_within(cwd, repo_root) or not cwd.is_dir():
        raise UsageError(f"--cwd must be a directory inside the repository: {cwd}")
    captures = []
    for relative in capture_paths or []:
        path = repo_root / relative
        if is_secret_file(relative) or path.is_symlink() or not is_within(path, repo_root):
            raise UsageError("--capture must be a non-secret file path inside the repository")
        captures.append(path.resolve().relative_to(repo_root).as_posix())
    network_mode = PROFILE_NETWORK_MODE[profile_name]
    if network_mode == "allow-listed" and not allowed_hosts:
        raise UsageError("provider_sandbox needs --allow-host for the sandbox endpoint the user approved")

    environment, added_variables = build_environment(list(extra_env or []), list(env_files or []), repo_root, keep_tz)
    compose_services = compose_service_names(repo_root)
    sources = [("run-env", added_variables), *gather_dotenv_sources(repo_root, [], set(not_loaded or set()))]
    preflight = evaluate_environment(sources, allowed_hosts, compose_services)
    base_details = {"argv": [redact_text(part) for part in argv], "profile": profile_name, "cwd": os.path.relpath(cwd, repo_root)}
    if preflight.blocked:
        result = CheckResult(check_id=check_id, tool="devskills.run-tests", execution_status=EXEC_NOT_RUN,
                             gate_result=GATE_BLOCKED, domain_result="unsafe_environment",
                             summary="preflight blocked the run before any process started",
                             findings=preflight.findings, details=base_details, started_at=started_at)
        return result, ["run-tests: BLOCKED by preflight (nothing was executed)", *format_findings(preflight.findings)]

    executable = _resolve_executable(argv, environment, cwd)
    if executable is None:
        result = CheckResult(check_id=check_id, tool="devskills.run-tests", execution_status=EXEC_TOOL_ERROR,
                             gate_result=GATE_BLOCKED, domain_result="executable_not_found",
                             summary=f"executable not found: {argv[0]}", details=base_details, started_at=started_at)
        return result, [f"run-tests: blocked, executable not found: {argv[0]}"]

    wrapper, enforcement = plan_network_enforcement(network_mode, allowed_hosts)
    if profile_name != "unit_offline" and not wrapper:
        result = CheckResult(check_id=check_id, tool="devskills.run-tests", execution_status=EXEC_NOT_RUN,
                             gate_result=GATE_BLOCKED, domain_result="network_isolation_unavailable",
                             summary="OS network isolation unavailable for this profile; nothing was executed",
                             details={**base_details, "network_enforcement": enforcement}, started_at=started_at)
        return result, ["run-tests: BLOCKED: Python socket guard is partial; use OS-isolated local execution"]
    if network_mode != "allow":
        python_path = added_variables.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(NETGUARD_DIR) + (os.pathsep + python_path if python_path else "")
        environment["DEVSKILLS_NET_MODE"] = network_mode
        environment["DEVSKILLS_NET_ALLOW"] = ",".join(sorted(allowed_hosts))
    environment["DEVSKILLS_TEST_PROFILE"] = profile_name

    if run_id:
        log_directory = logs_dir(repo_root, run_id) / check_id
    else:
        log_directory = ensure_state_dir(repo_root) / "logs" / f"{check_id}-{time.strftime('%Y%m%d-%H%M%S')}"
    log_directory.mkdir(parents=True, exist_ok=True)
    timeout_seconds = float(timeout or profile["testing"]["timeout_seconds"])
    cap_bytes = int(profile["testing"]["max_output_bytes"])
    allowed_roots = [repo_root, ensure_state_dir(repo_root)]

    full_argv = [*wrapper, executable, *argv[1:]]
    source_state = current_repo_state(repo_root) if junit_patterns else None
    test_sources_before = test_source_snapshot(repo_root) if junit_patterns else None
    capture_started = time.time()
    attempts: list[AttemptOutcome] = []
    for attempt_number in range(1, 2 + max(0, retries)):
        attempt = execute_once(attempt_number, full_argv, cwd, environment, timeout_seconds, cap_bytes,
                               log_directory, junit_patterns, allowed_roots)
        attempts.append(attempt)
        if classify_attempt(attempt, bool(junit_patterns), argv, exit_code_is_evidence)[2] in (GATE_PASS, GATE_WARN):
            break
        if attempt.timed_out:
            break

    execution_status, domain_result, gate_result, reason = decide_outcome(
        attempts, bool(junit_patterns), argv, exit_code_is_evidence)
    final_attempt = attempts[-1]
    capture_records, capture_errors = _capture_records(repo_root, captures, capture_started)
    if capture_errors and gate_result != GATE_FAIL:
        gate_result, domain_result, reason = GATE_BLOCKED, "capture_unavailable", "required capture missing, stale, linked or over 2 MiB"
    result = CheckResult(
        check_id=check_id,
        tool="devskills.run-tests",
        execution_status=execution_status,
        gate_result=gate_result,
        domain_result=domain_result,
        summary=reason,
        findings=preflight.findings,
        details=base_details | {
            "executable": executable,
            "network_mode": network_mode,
            "network_enforcement": enforcement,
            "allowed_hosts": sorted(allowed_hosts),
            "env_passed_explicitly": sorted(added_variables),
            "env_files": list(env_files or []),
            "timeout_seconds": timeout_seconds,
            "max_output_bytes_per_stream": cap_bytes,
            "exit_code_is_evidence": exit_code_is_evidence,
            "attempts": [attempt.to_dict() for attempt in attempts],
            "profile_warnings": profile_warnings,
            "source_state": source_state,
            "test_sources_before": test_sources_before,
            "test_sources_after": test_source_snapshot(repo_root) if junit_patterns else None,
            "captures": capture_records,
            "capture_errors": capture_errors,
        },
        evidence_refs=[final_attempt.stdout_log, final_attempt.stderr_log, *(final_attempt.junit.files if final_attempt.junit else []),
                       *[str(repo_root / path) for path in capture_records]],
        started_at=started_at,
    )
    lines = [
        f"run-tests [{profile_name}] {' '.join(base_details['argv'])}",
        f"  network: {network_mode} via {enforcement}",
        f"  attempts: {len(attempts)}, exit code: {final_attempt.exit_code}, {final_attempt.duration_seconds:.1f}s",
        f"  logs: {log_directory}",
    ]
    if final_attempt.leftover_processes_terminated:
        lines.append("  note: leftover child processes were terminated (possible resource leak in tests)")
    if final_attempt.stale_reports_ignored:
        lines.append(f"  note: ignored stale reports: {', '.join(final_attempt.stale_reports_ignored)}")
    if gate_result != GATE_PASS and final_attempt.output_tail:
        lines.append("  output tail:")
        lines.extend(f"    {line}" for line in final_attempt.output_tail[-20:])
    return result, lines


def run(args: argparse.Namespace) -> int:
    """CLI handler for `run-tests`: preflight, allowlisted env, network isolation, retries, recorded outcome."""
    repo_root = resolve_repo_root(args.repo)
    argv = list(args.command_argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise UsageError("give the test command after `--`, e.g. run-tests -- python -m pytest -q")
    result, lines = execute_check(
        repo_root, argv,
        check_id=getattr(args, "check_id", "tests.unit"),
        capture_paths=args.capture,
        profile_name=args.profile,
        junit_patterns=args.junit,
        timeout=args.timeout,
        extra_env=args.env,
        env_files=args.env_file,
        allowed_hosts=set(args.allow_host),
        cwd=(repo_root / args.cwd) if args.cwd else None,
        retries=args.retries,
        keep_tz=args.keep_tz,
        not_loaded=normalize_not_loaded(repo_root, args.dotenv_not_loaded, args.reason),
        run_id=args.run,
    )
    return emit_result(args, repo_root, result, lines)
