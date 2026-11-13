"""Rate-limit probe for a LOCAL endpoint (SEC-009, API-010, OWASP API4).

Sends a small, capped burst to an app running on this machine and reports
whether it answers 429 (with Retry-After) before the expected limit. It refuses
any non-loopback target: this is a correctness check of the limiter, not a load
test (PERF-008), and it stops at the first 429 unless told otherwise.
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from devskills.fsutil import resolve_repo_root, utc_now_iso
from devskills.models import EXEC_COMPLETED, GATE_FAIL, GATE_PASS, GATE_WARN, CheckResult, Finding, UsageError
from devskills.output import emit_result, format_findings

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_REQUESTS = 500
MAX_CONCURRENCY = 20
REQUEST_TIMEOUT_SECONDS = 10


def probe(url: str, method: str, body: bytes | None, headers: dict[str, str], total: int, concurrency: int,
          limit_status: int, stop_on_limit: bool) -> dict:
    """Send up to `total` requests with bounded concurrency; return per-request outcomes in order."""
    outcomes: list[dict | None] = [None] * total
    stop_event = threading.Event()

    def send(index: int) -> None:
        if stop_event.is_set():
            return
        request = Request(url, data=body, method=method, headers=headers)
        started = time.monotonic()
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status, retry_after = response.status, response.headers.get("Retry-After")
        except HTTPError as error:
            status, retry_after = error.code, error.headers.get("Retry-After")
        except (URLError, OSError) as error:
            status, retry_after = None, None
            outcomes[index] = {"index": index + 1, "status": None, "error": str(error)[:120],
                               "latency_ms": round((time.monotonic() - started) * 1000, 1)}
            return
        outcomes[index] = {"index": index + 1, "status": status, "retry_after": retry_after,
                           "latency_ms": round((time.monotonic() - started) * 1000, 1)}
        if status == limit_status and stop_on_limit:
            stop_event.set()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(send, range(total)))
    completed = [outcome for outcome in outcomes if outcome is not None]
    histogram: dict[str, int] = {}
    for outcome in completed:
        key = str(outcome["status"]) if outcome["status"] is not None else "error"
        histogram[key] = histogram.get(key, 0) + 1
    limited = [outcome for outcome in completed if outcome["status"] == limit_status]
    latencies = sorted(outcome["latency_ms"] for outcome in completed)
    return {
        "sent": len(completed),
        "status_histogram": histogram,
        "first_limited_request": min((outcome["index"] for outcome in limited), default=None),
        "retry_after_values": sorted({outcome.get("retry_after") for outcome in limited if outcome.get("retry_after")})[:5],
        "latency_ms_p50": statistics.median(latencies) if latencies else None,
        "latency_ms_p95": latencies[int(len(latencies) * 0.95) - 1] if len(latencies) >= 20 else None,
        "errors": [outcome for outcome in completed if outcome["status"] is None][:5],
    }


def cmd_rate_limit_probe(args: argparse.Namespace) -> int:
    """CLI handler for `rate-limit-probe`: pass when the limit status appears, fail when it never does."""
    repo_root = resolve_repo_root(args.repo)
    parts = urlsplit(args.url)
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in LOOPBACK_HOSTS:
        raise UsageError("rate-limit-probe only targets loopback URLs (http://localhost / 127.0.0.1); never shared or production hosts")
    if not 1 <= args.requests <= MAX_REQUESTS or not 1 <= args.concurrency <= MAX_CONCURRENCY:
        raise UsageError(f"--requests must be 1-{MAX_REQUESTS} and --concurrency 1-{MAX_CONCURRENCY}")
    headers = {}
    for header in args.header:
        name, separator, value = header.partition(":")
        if not separator:
            raise UsageError(f"--header {header!r}: expected 'Name: value'")
        headers[name.strip()] = value.strip()
    body = Path(args.body_file).read_bytes() if args.body_file else None
    started_at = utc_now_iso()
    outcome = probe(args.url, args.method.upper(), body, headers, args.requests, args.concurrency, args.limit_status,
                    stop_on_limit=not args.no_stop)

    findings: list[Finding] = []
    first_limited = outcome["first_limited_request"]
    if first_limited is None:
        gate = GATE_FAIL
        findings.append(Finding("SEC-009-NO-RATE-LIMIT", "high",
                                f"no {args.limit_status} after {outcome['sent']} requests to {parts.path or '/'}",
                                hint="Add per-account and per-IP limits (token bucket / sliding window) returning 429 + Retry-After."))
    elif args.expect_within and first_limited > args.expect_within:
        gate = GATE_WARN
        findings.append(Finding("SEC-009-LIMIT-TOO-HIGH", "medium",
                                f"first {args.limit_status} at request {first_limited}, expected within {args.expect_within}"))
    else:
        gate = GATE_PASS
    if first_limited is not None and not outcome["retry_after_values"]:
        findings.append(Finding("SEC-009-NO-RETRY-AFTER", "low", "rate-limited responses carry no Retry-After header",
                                hint="Send Retry-After so clients back off instead of hammering (REL-001)."))
    if outcome["errors"]:
        findings.append(Finding("SEC-009-PROBE-ERRORS", "medium", f"{len(outcome['errors'])}+ requests failed: {outcome['errors'][0]['error']}"))
    result = CheckResult(
        check_id=getattr(args, "check_id", "security.rate_limit"),
        tool="devskills.rate-limit-probe",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="limited" if first_limited else "not_limited",
        summary=f"{outcome['sent']} requests, statuses {outcome['status_histogram']}, first {args.limit_status} at {first_limited}",
        findings=findings,
        details=outcome | {"url": f"{parts.scheme}://{parts.netloc}{parts.path}", "method": args.method.upper(),
                           "concurrency": args.concurrency, "limit_status": args.limit_status},
        started_at=started_at,
    )
    lines = [f"rate-limit-probe: {result.summary}"]
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)
