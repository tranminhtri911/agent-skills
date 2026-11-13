"""Test-environment preflight (SAFE-001, SAFE-002, SAFE-005, SAFE-010, SAFE-013).

Before any test, simulator-backed or not, prove that the process cannot reach
production: no live payment keys, no production environment marker, no
database/queue/SMTP host outside the local machine or the project's own
docker-compose services unless the user approved it as a sandbox. Values are
classified but never printed (only scheme and host).
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from devskills.fsutil import read_text_limited, resolve_repo_root, utc_now_iso
from devskills.models import (
    EXEC_COMPLETED,
    GATE_BLOCKED,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    Finding,
    UsageError,
)
from devskills.output import emit_result, format_findings

# Dotenv files that common frameworks load automatically during tests.
AUTO_LOADED_DOTENV_FILES = (".env", ".env.local", ".env.test", ".env.testing", ".env.test.local")

_LOCAL_NAMES = frozenset({"localhost", "host.docker.internal", "host.containers.internal", "gateway.docker.internal"})
_RESERVED_SUFFIXES = (".localhost", ".local", ".test", ".example", ".invalid", ".internal.test")
_PRODUCTION_MARKER = re.compile(r"(?i)(?:^|[.\-_])(prod|production|live)(?:[.\-_\d]|$)")
_PRODUCTION_ENV_VALUE = re.compile(r"(?i)^(prod|production|live|prd)$")

_ENV_MARKER_KEYS = frozenset({
    "APP_ENV", "ENV", "ENVIRONMENT", "NODE_ENV", "RAILS_ENV", "RACK_ENV", "FLASK_ENV", "APP_STAGE", "STAGE",
    "ASPNETCORE_ENVIRONMENT", "DOTNET_ENVIRONMENT", "SPRING_PROFILES_ACTIVE", "MIX_ENV", "GO_ENV", "DEPLOY_ENV",
})
_TARGET_KEY = re.compile(
    r"(?i)(DATABASE_URL|DB_URL|_DSN$|^DSN$|DB_HOST|DATABASE_HOST|POSTGRES_HOST|PGHOST|MYSQL_HOST|MARIADB_HOST|"
    r"MONGO\w*_(URI|URL|HOST)|REDIS_(URL|HOST)|AMQP_URL|RABBITMQ_(URL|HOST)|KAFKA_(BROKERS|BOOTSTRAP\w*)|"
    r"ELASTIC\w*_(URL|HOST)|SQLSERVER_HOST|MSSQL_HOST|ORACLE_HOST|SMTP_HOST|MAIL_HOST|EMAIL_HOST|"
    r"_API_BASE_URL$|_BASE_URL$|_ENDPOINT$)"
)
_PROVIDER_SECRET_KEY = re.compile(
    r"(?i)^(STRIPE|PAYPAL|BRAINTREE|ADYEN|SQUARE|VNPAY|MOMO|ZALOPAY|ONEPAY|PAYOS|SENDGRID|MAILGUN|POSTMARK|"
    r"TWILIO|VONAGE|NEXMO|ESMS|SPEEDSMS|FIREBASE|FCM|APNS|ONESIGNAL|SLACK_WEBHOOK)\w*(KEY|SECRET|TOKEN|SID|PASSWORD)\w*$"
)
_CLOUD_CREDENTIAL_KEY = re.compile(
    r"(?i)^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|GOOGLE_APPLICATION_CREDENTIALS|"
    r"AZURE_CLIENT_SECRET|AZURE_STORAGE_KEY|DIGITALOCEAN_TOKEN|CLOUDFLARE_API_TOKEN|KUBECONFIG|VERCEL_TOKEN|NETLIFY_AUTH_TOKEN)$"
)
_LIVE_KEY_VALUE = re.compile(r"^(sk|rk)_live_|live_[A-Za-z0-9]{16,}")


@dataclass
class EnvironmentDecision:
    """Aggregated preflight outcome; `blocked` means no test may start."""

    findings: list[Finding] = field(default_factory=list)
    observed_keys: int = 0

    @property
    def blocked(self) -> bool:
        return any(finding.severity in ("critical", "high") for finding in self.findings)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines (optional `export`, quotes, comments); no interpolation."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] in "'\"" and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", key):
            values[key] = value
    return values


def compose_service_names(repo_root: Path) -> set[str]:
    """Service names declared in docker-compose files: valid dotless hosts inside the project network."""
    names: set[str] = set()
    for file_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
                      "docker-compose.test.yml", "docker-compose.override.yml"):
        text = read_text_limited(repo_root / file_name)
        if not text:
            continue
        in_services = False
        for line in text.splitlines():
            if re.match(r"^services:\s*$", line):
                in_services = True
                continue
            if in_services and re.match(r"^\S", line):
                in_services = False
            match = re.match(r"^  ([A-Za-z0-9][A-Za-z0-9_.-]*):\s*$", line) if in_services else None
            if match:
                names.add(match.group(1).lower())
    return names


def classify_host(host: str, allowed_hosts: set[str], compose_services: set[str]) -> str:
    """Return local | compose | allowed | production | remote for a hostname or IP."""
    normalized = host.strip().strip("[]").lower().rstrip(".")
    if not normalized:
        return "local"
    if _PRODUCTION_MARKER.search(normalized):
        # A production-looking name is never accepted, even when "allowed" (SAFE-002).
        return "production"
    if normalized in _LOCAL_NAMES or normalized.endswith(_RESERVED_SUFFIXES):
        return "local"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback or address.is_unspecified:
            return "local"
        return "allowed" if normalized in allowed_hosts else "remote"
    if normalized in allowed_hosts:
        return "allowed"
    if "." not in normalized and normalized in compose_services:
        return "compose"
    return "remote"


def _hosts_in_value(value: str) -> list[tuple[str, str]]:
    """Extract (scheme, host) pairs from a URL/DSN or a bare host value."""
    if "://" in value:
        try:
            parts = urlsplit(value)
        except ValueError:
            return []
        netloc = parts.netloc.rsplit("@", 1)[-1]
        hosts = []
        # Multi-host DSNs (mongodb, kafka) list hosts separated by commas.
        for host_port in netloc.split(","):
            host = host_port.strip()
            if host.startswith("["):
                host = host[1:].split("]", 1)[0]
            else:
                host = host.split(":", 1)[0]
            if host:
                hosts.append((parts.scheme, host))
        return hosts
    hosts = []
    for item in value.split(","):
        host = item.strip().split(":", 1)[0]
        if host and re.match(r"^[A-Za-z0-9.\-]+$", host):
            hosts.append(("", host))
    return hosts


def evaluate_environment(
    sources: Iterable[tuple[str, Mapping[str, str]]],
    allowed_hosts: set[str],
    compose_services: set[str],
) -> EnvironmentDecision:
    """Classify every variable from every source; never stores or prints values."""
    decision = EnvironmentDecision()
    for source_name, variables in sources:
        for key, value in variables.items():
            decision.observed_keys += 1
            if not value:
                continue
            location = f"{source_name}:{key}"
            if _LIVE_KEY_VALUE.search(value):
                decision.findings.append(Finding(
                    "SAFE-005-LIVE-KEY", "critical", "live payment/provider key present", location,
                    hint="Use the provider's test mode key or the local simulator (ds.py simulate payment).",
                ))
                continue
            if key.upper() in _ENV_MARKER_KEYS and _PRODUCTION_ENV_VALUE.match(value.strip()):
                decision.findings.append(Finding(
                    "SAFE-001-PRODUCTION-ENV", "critical", f"environment marker says production ({key})", location,
                    hint="Run tests with a test/testing environment; never point a test run at production.",
                ))
                continue
            if _TARGET_KEY.search(key):
                for scheme, host in _hosts_in_value(value):
                    category = classify_host(host, allowed_hosts, compose_services)
                    shown = f"{scheme + '://' if scheme else ''}{host}"
                    if category == "production":
                        decision.findings.append(Finding(
                            "SAFE-002-PRODUCTION-TARGET", "critical", f"target looks like production: {shown}", location,
                            hint="Point the test at a disposable local/container service.",
                        ))
                    elif category == "remote":
                        decision.findings.append(Finding(
                            "SAFE-002-REMOTE-TARGET", "high", f"target outside this machine/project network: {shown}",
                            location,
                            hint="Use a local container, or pass --allow-host only for a sandbox the user approved.",
                        ))
                    elif category == "allowed":
                        decision.findings.append(Finding(
                            "SAFE-002-ALLOWED-TARGET", "info", f"user-approved sandbox target: {shown}", location,
                        ))
                continue
            if _PROVIDER_SECRET_KEY.match(key):
                decision.findings.append(Finding(
                    "SAFE-005-PROVIDER-CREDENTIAL", "high",
                    "payment/messaging provider credential present; tests could charge or message real people",
                    location,
                    hint="Remove it from the test environment and use the simulator or the provider's sandbox profile.",
                ))
                continue
            if _CLOUD_CREDENTIAL_KEY.match(key):
                decision.findings.append(Finding(
                    "SAFE-005-CLOUD-CREDENTIAL", "medium",
                    "cloud credential present; tests could create or delete real resources",
                    location,
                    hint="run-tests strips it by default; do not pass it with --env unless the user approved.",
                ))
    return decision


def gather_dotenv_sources(
    repo_root: Path, extra_env_files: list[str], not_loaded: set[str]
) -> list[tuple[str, dict[str, str]]]:
    """Read dotenv files that tests may load, skipping files the user declared unused."""
    sources: list[tuple[str, dict[str, str]]] = []
    candidates = [*AUTO_LOADED_DOTENV_FILES, *extra_env_files]
    for name in dict.fromkeys(candidates):
        path = (repo_root / name) if not Path(name).is_absolute() else Path(name)
        relative_name = os.path.relpath(path, repo_root)
        if relative_name in not_loaded or not path.is_file():
            continue
        text = read_text_limited(path, 512 * 1024)
        if text is not None:
            sources.append((relative_name, parse_dotenv(text)))
    return sources


def normalize_not_loaded(repo_root: Path, paths: list[str], reason: str | None) -> set[str]:
    if paths and not (reason and reason.strip()):
        raise UsageError("--dotenv-not-loaded requires --reason explaining why the tests never load those files")
    return {os.path.relpath((repo_root / path).resolve(), repo_root) for path in paths}


def run(args: argparse.Namespace) -> int:
    """CLI handler for `preflight`: block when dotenv files the tests may load point at production/remote targets."""
    repo_root = resolve_repo_root(args.repo)
    started_at = utc_now_iso()
    allowed_hosts = {host.lower() for host in args.allow_host}
    not_loaded = normalize_not_loaded(repo_root, args.dotenv_not_loaded, args.reason)
    compose_services = compose_service_names(repo_root)

    dotenv_sources = gather_dotenv_sources(repo_root, args.env_file, not_loaded)
    file_decision = evaluate_environment(dotenv_sources, allowed_hosts, compose_services)
    # The agent's own environment is informational: run-tests strips it to an allowlist.
    shell_decision = evaluate_environment([("shell-env", dict(os.environ))], allowed_hosts, compose_services)
    for finding in shell_decision.findings:
        finding.severity = "info" if finding.severity != "critical" else "medium"
        finding.message += " (agent shell; stripped by run-tests unless passed with --env)"

    findings = file_decision.findings + shell_decision.findings
    gate = GATE_BLOCKED if file_decision.blocked else (GATE_WARN if findings else GATE_PASS)
    result = CheckResult(
        check_id=getattr(args, "check_id", "env.preflight"),
        tool="devskills.preflight",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="unsafe_targets" if file_decision.blocked else "no_production_targets_found",
        summary=(f"{len(dotenv_sources)} dotenv file(s), {file_decision.observed_keys} keys checked; "
                 f"{len(file_decision.findings)} file finding(s), {len(shell_decision.findings)} shell note(s)"),
        findings=findings,
        details={
            "dotenv_files_checked": [name for name, _ in dotenv_sources],
            "dotenv_declared_not_loaded": sorted(not_loaded),
            "dotenv_not_loaded_reason": args.reason,
            "allowed_hosts": sorted(allowed_hosts),
            "compose_services": sorted(compose_services),
            "limitations": "Classifies names and hosts only; it does not prove which config the test framework loads.",
        },
        started_at=started_at,
    )
    lines = [f"preflight: {result.summary}"]
    lines.extend(format_findings(findings))
    if gate == GATE_BLOCKED:
        lines.append("BLOCKED: fix the targets above before running any test, script or batch.")
    return emit_result(args, repo_root, result, lines)
