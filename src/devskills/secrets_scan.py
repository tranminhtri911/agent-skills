"""Secret detection and redaction (SEC-005, SEC-010, AGENT-003).

The same patterns serve three purposes: scanning changed files, redacting
command logs written by run-tests, and checking page text before screenshots
are shared. A detected value is never printed in full.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from devskills.fsutil import (
    is_lockfile,
    is_secret_file,
    read_text_limited,
    resolve_repo_root,
    run_git,
    select_target_files,
    utc_now_iso,
)
from devskills.models import (
    EXEC_COMPLETED,
    GATE_FAIL,
    CheckResult,
    Finding,
    gate_from_findings,
)
from devskills.output import emit_result, format_findings, severity_summary

# Inline exception marker; must be followed by a reason (plan §4.5, SEC-012).
ALLOW_MARKER = "devskills:allow-secret"


@dataclass(frozen=True)
class SecretPattern:
    rule_id: str
    severity: str
    description: str
    regex: re.Pattern[str]
    # Regex group holding the secret value (0 = whole match).
    value_group: int = 0


SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("SECRET-PRIVATE-KEY", "critical", "private key block",
                  re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    SecretPattern("SECRET-STRIPE-LIVE-KEY", "critical", "Stripe live secret/restricted key",
                  re.compile(r"\b((?:sk|rk)_live_[A-Za-z0-9]{16,})"), 1),
    SecretPattern("SECRET-AWS-ACCESS-KEY", "high", "AWS access key id",
                  re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"), 1),
    SecretPattern("SECRET-AWS-SECRET-KEY", "high", "AWS secret access key",
                  re.compile(r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})"), 1),
    SecretPattern("SECRET-GITHUB-TOKEN", "high", "GitHub token",
                  re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), 1),
    SecretPattern("SECRET-SLACK-TOKEN", "high", "Slack token",
                  re.compile(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})"), 1),
    SecretPattern("SECRET-SLACK-WEBHOOK", "medium", "Slack incoming webhook URL",
                  re.compile(r"(https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,})"), 1),
    SecretPattern("SECRET-GOOGLE-API-KEY", "high", "Google API key",
                  re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})"), 1),
    SecretPattern("SECRET-ANTHROPIC-KEY", "high", "Anthropic API key",
                  re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{20,})"), 1),
    SecretPattern("SECRET-OPENAI-KEY", "high", "OpenAI-style API key",
                  re.compile(r"\b(sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,})"), 1),
    SecretPattern("SECRET-STRIPE-TEST-KEY", "medium", "Stripe test secret key (still a credential)",
                  re.compile(r"\b((?:sk|rk)_test_[A-Za-z0-9]{16,})"), 1),
    SecretPattern("SECRET-JWT", "medium", "JSON Web Token",
                  re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"), 1),
    SecretPattern("SECRET-URL-CREDENTIALS", "high", "connection string with an embedded password",
                  re.compile(r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?|amqps?|mssql|sqlserver)"
                             r"://[^\s:/@'\"]+:([^\s@/'\"]+)@([^\s/'\":]+)"), 1),
    SecretPattern("SECRET-GENERIC-ASSIGNMENT", "medium", "hard-coded credential value",
                  re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|"
                             r"client[_-]?secret|private[_-]?key)\b['\"]?\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]"), 1),
)

# Values that are obviously placeholders, not credentials.
_PLACEHOLDER = re.compile(
    r"(?i)^(?:x+|\*+|\.+|changeme|change[_-]?me|password\d*|secret|example\w*|dummy\w*|test\w*|placeholder|"
    r"your[_-].*|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|\$[A-Z_]+|null|none|redacted|fake\w*|sample\w*|todo|"
    r"process\.env\..*|env\(.*\)|os\.environ.*|getenv.*|settings\..*|config\..*)$"
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"})


def redact_value(value: str) -> str:
    """Show only a short prefix and the length, enough to locate the value safely."""
    if len(value) < 8:
        return "[redacted]"
    return f"{value[:4]}...[{len(value)} chars]"


def redact_text(text: str) -> str:
    """Replace every detected secret value in `text` (used for logs and page text)."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        def _replace(match: re.Match[str], group: int = pattern.value_group) -> str:
            whole = match.group(0)
            value = match.group(group) if group else whole
            if not value or _PLACEHOLDER.match(value):
                return whole
            return whole.replace(value, redact_value(value))

        redacted = pattern.regex.sub(_replace, redacted)
    return redacted


def scan_text(text: str, rel_path: str | None) -> tuple[list[Finding], list[Finding]]:
    """Return (findings, suppressed findings) for one text blob."""
    findings: list[Finding] = []
    suppressed: list[Finding] = []
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        for pattern in SECRET_PATTERNS:
            for match in pattern.regex.finditer(line):
                value = match.group(pattern.value_group) if pattern.value_group else match.group(0)
                if not value or _PLACEHOLDER.match(value):
                    continue
                severity = pattern.severity
                if pattern.rule_id == "SECRET-URL-CREDENTIALS" and match.group(2).lower() in _LOCAL_HOSTS:
                    # Local docker credentials are common in compose files; still visible, but not high.
                    severity = "low"
                finding = Finding(
                    rule_id=pattern.rule_id,
                    severity=severity,
                    message=f"{pattern.description}: {redact_value(value)}",
                    path=rel_path,
                    line=line_number,
                    hint="Move the value to a secret manager or env reference and rotate it if it was ever committed.",
                )
                if ALLOW_MARKER in line and line.split(ALLOW_MARKER, 1)[1].strip(" :-#/*"):
                    finding.hint = "suppressed with reason: " + line.split(ALLOW_MARKER, 1)[1].strip(" :-#/*")
                    suppressed.append(finding)
                else:
                    findings.append(finding)
    return _dedupe(findings), suppressed


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Keep one finding per (path, line, rule); overlapping patterns otherwise double count."""
    seen: set[tuple[str | None, int | None, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.path, finding.line, finding.rule_id)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def _tracked_env_files(repo_root: Path) -> list[str]:
    tracked = run_git(repo_root, ["ls-files", "-z"])
    if not tracked:
        return []
    return [path for path in tracked.split("\0") if path and is_secret_file(path)]


def run(args: argparse.Namespace) -> int:
    """CLI handler for `scan-secrets`: scan selected files plus tracked secret files; values are redacted."""
    repo_root = resolve_repo_root(args.repo)
    started_at = utc_now_iso()
    scope = "all" if args.all else "changed"
    targets = select_target_files(repo_root, args.paths, scope, args.base)

    findings: list[Finding] = []
    suppressed: list[Finding] = []
    scanned = 0
    for rel_path in targets:
        # Secret-bearing files are reported by name below; their content is never read.
        if is_secret_file(rel_path) or is_lockfile(rel_path) or rel_path.endswith((".min.js", ".map")):
            continue
        text = read_text_limited(repo_root / rel_path, 2 * 1024 * 1024)
        if text is None:
            continue
        scanned += 1
        file_findings, file_suppressed = scan_text(text, rel_path)
        findings.extend(file_findings)
        suppressed.extend(file_suppressed)

    for env_path in _tracked_env_files(repo_root):
        findings.append(Finding(
            rule_id="SECRET-TRACKED-SECRET-FILE",
            severity="high",
            message="secret-bearing file is tracked by git (content not read)",
            path=env_path,
            hint="Remove it from git (git rm --cached), add it to .gitignore, rotate the credentials it held.",
        ))

    gate = gate_from_findings(findings, fail_on="high")
    result = CheckResult(
        check_id=getattr(args, "check_id", "security.secrets"),
        tool="devskills.scan-secrets",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="findings" if findings else "clean_in_scanned_scope",
        summary=f"{scanned} files scanned ({scope}); {severity_summary(findings)}; {len(suppressed)} suppressed",
        findings=findings,
        details={
            "scope": scope,
            "files_scanned": scanned,
            "suppressed": [finding.to_dict() for finding in suppressed],
            "limitations": "pattern-based; a clean result means no known pattern matched, not that no secret exists",
        },
        started_at=started_at,
    )
    lines = [f"scan-secrets: {result.summary}"]
    lines.extend(format_findings(findings))
    if gate == GATE_FAIL:
        lines.append("Do not commit until these are removed and rotated.")
    return emit_result(args, repo_root, result, lines)
