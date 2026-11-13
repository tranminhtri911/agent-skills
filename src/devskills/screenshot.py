"""Deterministic screenshots with Playwright for Python (plan §20.1-§20.6).

Pipeline: isolated browser context → pinned viewport/locale/time zone/color
scheme/reduced motion → requests to non-local hosts blocked → wait for an
explicit UI condition and fonts → animations disabled → capture → manifest
with hashes, console/page errors, blocked requests and a DOM-text secret scan.
Without a baseline the status is CAPTURE_ONLY, which is never a visual pass.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from devskills import SCHEMA_VERSION
from devskills.fsutil import atomic_write_json, ensure_state_dir, resolve_repo_root, run_git, sha256_file, utc_now_iso
from devskills.models import (
    EXEC_COMPLETED,
    EXEC_TOOL_ERROR,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    Finding,
    UsageError,
)
from devskills.output import emit_result, format_findings
from devskills.profile import load_profile
from devskills.runs import artifacts_dir
from devskills.secrets_scan import scan_text
from devskills.visual import CAPTURE_ONLY, NEEDS_BASELINE, VISUAL_BLOCKED, VISUAL_FAIL, VISUAL_PASS, compare_files

# laptop is the smallest common laptop class (Tailwind `xl`); desktop a large laptop/monitor.
VIEWPORT_PRESETS = {"mobile": (390, 844), "tablet": (768, 1024), "laptop": (1280, 800), "desktop": (1440, 900)}
# A web screen is checked on a phone and a laptop unless the task names other devices.
DEFAULT_VIEWPORTS = ("mobile", "laptop")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})
ALWAYS_ALLOWED_SCHEMES = frozenset({"data", "blob", "about", "chrome-extension"})
FREEZE_CSS = (
    "*, *::before, *::after { animation: none !important; transition: none !important; "
    "caret-color: transparent !important; scroll-behavior: auto !important; }"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def parse_viewports(values: list[str]) -> list[tuple[str, int, int]]:
    """Turn mobile/tablet/laptop/desktop presets or WIDTHxHEIGHT strings into (name, width, height); default mobile + laptop."""
    if not values:
        values = list(DEFAULT_VIEWPORTS)
    parsed = []
    for value in values:
        if value in VIEWPORT_PRESETS:
            width, height = VIEWPORT_PRESETS[value]
            parsed.append((value, width, height))
            continue
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", value)
        if not match:
            raise UsageError(f"--viewport {value!r}: use mobile, tablet, laptop, desktop or WIDTHxHEIGHT")
        parsed.append((value, int(match.group(1)), int(match.group(2))))
    return parsed


def host_allowed(url: str, allowed_hosts: set[str]) -> bool:
    parts = urlsplit(url)
    if parts.scheme in ALWAYS_ALLOWED_SCHEMES:
        return True
    host = (parts.hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost") or host in allowed_hosts


def _redacted_url(url: str) -> str:
    """Drop query values and fragments: they often carry tokens."""
    parts = urlsplit(url)
    query = "&".join(f"{item.split('=', 1)[0]}=…" for item in parts.query.split("&") if item) if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _case_name(url: str) -> str:
    path = urlsplit(url).path.strip("/") or "home"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", path)[:80].strip("-") or "page"


def capture(args: argparse.Namespace, out_dir: Path, allowed_hosts: set[str], visual_profile: dict[str, Any],
            repo_root: Path) -> list[dict[str, Any]]:
    """Capture one screenshot per viewport; raises ImportError when Playwright is missing."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    case_name = args.name or _case_name(args.url)
    manifests: list[dict[str, Any]] = []
    head = (run_git(repo_root, ["rev-parse", "HEAD"]) or "").strip() or None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for viewport_name, width, height in parse_viewports(args.viewport):
                blocked_requests: list[str] = []
                failed_requests: list[str] = []
                console_errors: list[str] = []
                page_errors: list[str] = []
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    locale=args.locale,
                    timezone_id=args.timezone,
                    color_scheme=args.color_scheme,
                    reduced_motion="reduce",
                    service_workers="block",
                )
                try:
                    # Handlers below close over this iteration's lists on purpose: the context is closed
                    # before the next iteration, and Playwright inspects handler arity, so no default-arg binding.
                    def route_handler(route, request) -> None:
                        if host_allowed(request.url, allowed_hosts):
                            route.continue_()
                        else:
                            blocked_requests.append(_redacted_url(request.url))
                            route.abort("blockedbyclient")

                    context.route("**/*", route_handler)
                    page = context.new_page()
                    page.on("console", lambda message: console_errors.append(message.text[:300]) if message.type == "error" else None)
                    page.on("pageerror", lambda error: page_errors.append(str(error)[:300]))
                    page.on("requestfailed", lambda request: failed_requests.append(_redacted_url(request.url))
                            if _redacted_url(request.url) not in blocked_requests else None)
                    navigation_error = None
                    try:
                        page.goto(args.url, wait_until="load", timeout=args.timeout_ms)
                        if args.wait_for:
                            page.locator(args.wait_for).first.wait_for(state="visible", timeout=args.timeout_ms)
                        if args.wait_text:
                            page.get_by_text(args.wait_text).first.wait_for(state="visible", timeout=args.timeout_ms)
                        page.add_style_tag(content=FREEZE_CSS)
                        page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
                        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                    except PlaywrightError as error:
                        navigation_error = str(error).splitlines()[0][:300]

                    file_stem = f"{case_name}-{viewport_name}"
                    image_path = out_dir / f"{file_stem}.png"
                    manifest: dict[str, Any] = {
                        "schema_version": SCHEMA_VERSION,
                        "case_id": case_name,
                        "url": _redacted_url(args.url),
                        "viewport": {"width": width, "height": height},
                        "device_scale_factor": 1,
                        "locale": args.locale,
                        "timezone": args.timezone,
                        "color_scheme": args.color_scheme,
                        "browser": "chromium",
                        "browser_version": browser.version,
                        "playwright_version": importlib.metadata.version("playwright"),
                        "platform": f"{platform.system()}-{platform.machine()}",
                        "repository_head": head,
                        "captured_at": utc_now_iso(),
                        "wait_conditions": {"selector": args.wait_for, "text": args.wait_text},
                        "masked_selectors": args.mask,
                        "console_errors": console_errors,
                        "page_errors": page_errors,
                        "blocked_requests": sorted(set(blocked_requests)),
                        "failed_requests": sorted(set(failed_requests))[:50],
                    }
                    manifest["profile_id"] = (f"chromium-{browser.version}-{manifest['platform']}-{width}x{height}@1-"
                                              f"{args.locale}-{args.timezone}-{args.color_scheme}")
                    if navigation_error:
                        manifest |= {"behavior_status": "blocked", "visual_status": VISUAL_BLOCKED, "error": navigation_error}
                        manifests.append(manifest)
                        continue
                    page.screenshot(
                        path=str(image_path),
                        full_page=args.full_page,
                        animations="disabled",
                        caret="hide",
                        mask=[page.locator(selector) for selector in args.mask],
                        scale="css",
                    )
                    page_text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
                    secret_findings, _ = scan_text(page_text, None)
                    manifest["privacy_check"] = {
                        "dom_text_secret_findings": [finding.rule_id for finding in secret_findings],
                        "dom_text_email_count": len(EMAIL_PATTERN.findall(page_text)),
                        "synthetic_data_verified": False,
                        "note": "Pixels are not OCR-scanned; confirm the page uses synthetic data before sharing.",
                    }
                    manifest["artifacts"] = {"current": str(image_path), "sha256": sha256_file(image_path),
                                             "size_bytes": image_path.stat().st_size}
                    manifest["behavior_status"] = "pass"
                    manifest["visual_status"] = CAPTURE_ONLY
                    if args.baseline_dir:
                        baseline_path = Path(args.baseline_dir) / image_path.name
                        baseline_manifest_path = baseline_path.with_suffix(".json")
                        baseline_manifest = None
                        if baseline_manifest_path.is_file():
                            import json

                            baseline_manifest = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
                        comparison = compare_files(baseline_path, image_path, out_dir / f"{file_stem}.diff.png",
                                                   visual_profile["pixel_threshold"], visual_profile["max_diff_ratio"], [],
                                                   baseline_manifest, manifest)
                        manifest["visual_status"] = comparison["visual_status"]
                        manifest["comparison"] = comparison
                    atomic_write_json(image_path.with_suffix(".json"), manifest)
                    manifests.append(manifest)
                finally:
                    context.close()
        finally:
            browser.close()
    return manifests


def gate_for_manifests(manifests: list[dict[str, Any]], comparison_requested: bool) -> tuple[str, list[Finding]]:
    """Map captures to a gate; capture-only is a pass for the capture gate, never a visual pass."""
    findings: list[Finding] = []
    gate = GATE_PASS
    for manifest in manifests:
        location = manifest.get("artifacts", {}).get("current") or manifest["url"]
        if manifest.get("visual_status") == VISUAL_BLOCKED:
            findings.append(Finding("UI-CAPTURE-BLOCKED", "high", f"capture failed: {manifest.get('error')}", location))
            gate = GATE_BLOCKED
            continue
        if manifest["page_errors"]:
            findings.append(Finding("UI-PAGE-ERROR", "medium", f"{len(manifest['page_errors'])} uncaught page error(s): {manifest['page_errors'][0]}", location))
        if manifest["console_errors"]:
            findings.append(Finding("UI-CONSOLE-ERROR", "medium", f"{len(manifest['console_errors'])} console error(s): {manifest['console_errors'][0]}", location))
        if manifest["blocked_requests"]:
            findings.append(Finding("UI-EXTERNAL-REQUEST-BLOCKED", "low",
                                    f"{len(manifest['blocked_requests'])} request(s) to non-local hosts blocked, e.g. {manifest['blocked_requests'][0]}",
                                    location, hint="Serve fonts/assets locally or mock them, so captures stay deterministic."))
        if manifest.get("privacy_check", {}).get("dom_text_secret_findings"):
            findings.append(Finding("UI-SECRET-ON-PAGE", "high", "secret-like value visible in page text; quarantine the screenshot", location))
        status = manifest.get("visual_status")
        if status == VISUAL_FAIL:
            findings.append(Finding("UI-VISUAL-REGRESSION", "high", manifest["comparison"]["reason"], location))
            gate = GATE_FAIL
        elif comparison_requested and status not in (VISUAL_PASS,):
            findings.append(Finding("UI-VISUAL-NOT-COMPARED", "medium", f"{status}: {manifest.get('comparison', {}).get('reason', '')}", location))
            if gate == GATE_PASS:
                gate = GATE_BLOCKED
    if gate == GATE_PASS and any(finding.severity in ("high", "critical") for finding in findings):
        gate = GATE_FAIL
    elif gate == GATE_PASS and findings:
        gate = GATE_WARN
    return gate, findings


def run(args: argparse.Namespace) -> int:
    """CLI handler for `screenshot`: local URLs only; BLOCKED (never faked) when Playwright/browser is missing."""
    repo_root = resolve_repo_root(args.repo)
    profile, _warnings = load_profile(repo_root)
    started_at = utc_now_iso()
    allowed_hosts = {host.lower() for host in args.allow_host}
    check_id = getattr(args, "check_id", "ui.screenshot")
    if not host_allowed(args.url, allowed_hosts):
        raise UsageError(f"{args.url}: only local URLs are captured by default; pass --allow-host for a host the user approved")
    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif args.run:
        out_dir = artifacts_dir(repo_root, args.run) / "screenshots"
    else:
        out_dir = ensure_state_dir(repo_root) / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifests = capture(args, out_dir, allowed_hosts, profile["visual"], repo_root)
    except ImportError:
        result = CheckResult(check_id=check_id, tool="devskills.screenshot", execution_status=EXEC_TOOL_ERROR,
                             gate_result=GATE_BLOCKED, domain_result=VISUAL_BLOCKED,
                             summary="Playwright for Python is not installed in this interpreter",
                             details={"install": ["python3 -m pip install playwright", "python3 -m playwright install chromium"]},
                             started_at=started_at)
        return emit_result(args, repo_root, result, [
            "screenshot: BLOCKED — Playwright for Python is missing (no image was produced).",
            "  install: python3 -m pip install playwright && python3 -m playwright install chromium",
            "  or run the repository's own Playwright Test suite through `run-tests`.",
        ])
    except Exception as error:  # noqa: BLE001 — browser launch problems (missing binaries) are environment issues, not passes.
        message = str(error).splitlines()[0][:300]
        result = CheckResult(check_id=check_id, tool="devskills.screenshot", execution_status=EXEC_TOOL_ERROR,
                             gate_result=GATE_BLOCKED, domain_result=VISUAL_BLOCKED, summary=message,
                             details={"hint": "python3 -m playwright install chromium"}, started_at=started_at)
        return emit_result(args, repo_root, result, [f"screenshot: BLOCKED — {message}"])

    gate, findings = gate_for_manifests(manifests, comparison_requested=bool(args.baseline_dir))
    statuses = sorted({manifest.get("visual_status", "?") for manifest in manifests})
    result = CheckResult(
        check_id=check_id,
        tool="devskills.screenshot",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result=",".join(statuses),
        summary=f"{len(manifests)} capture(s); visual status {', '.join(statuses)}",
        findings=findings,
        details={"manifests": manifests, "out_dir": str(out_dir)},
        evidence_refs=[manifest.get("artifacts", {}).get("current") for manifest in manifests if manifest.get("artifacts")],
        started_at=started_at,
    )
    lines = [f"screenshot: {len(manifests)} capture(s) in {out_dir}"]
    for manifest in manifests:
        lines.append(f"  {manifest['viewport']['width']}x{manifest['viewport']['height']}: {manifest.get('visual_status')} "
                     f"{manifest.get('artifacts', {}).get('current', manifest.get('error', ''))}")
    if NEEDS_BASELINE in statuses:
        lines.append("  NEEDS_BASELINE: show the capture to a reviewer; never accept a baseline on your own.")
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)
