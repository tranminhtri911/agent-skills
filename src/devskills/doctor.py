"""Capability report: what this machine can verify, without calling any live service.

`doctor` only inspects local tools and metadata (plan §24.6). Missing optional
capabilities make the related checks `blocked` later; they are never faked.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from devskills import MIN_PYTHON, __version__
from devskills.codegraph import detect, resolve_mode
from devskills.fsutil import resolve_repo_root, sha256_file
from devskills.profile import load_profile

OPTIONAL_TOOLS = ("git", "rg", "node", "npm", "npx", "docker", "uv", "psql", "mysql")


def _tool_version(executable: str) -> str | None:
    try:
        completed = subprocess.run([executable, "--version"], capture_output=True, timeout=5, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr).decode("utf-8", errors="replace").strip().splitlines()
    return output[0][:120] if output else None


def _playwright_browsers() -> list[str]:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates = [Path(configured)] if configured and configured != "0" else []
    home = Path.home()
    candidates += [home / "Library/Caches/ms-playwright", home / ".cache/ms-playwright", home / "AppData/Local/ms-playwright"]
    for directory in candidates:
        if directory.is_dir():
            return sorted(entry.name for entry in directory.iterdir() if entry.name.startswith(("chromium", "firefox", "webkit")))
    return []


def _runtime_location() -> dict[str, Any]:
    package_dir = Path(__file__).resolve().parent
    manifest = package_dir.parent / "MANIFEST.json"
    info: dict[str, Any] = {"package_dir": str(package_dir), "vendored": manifest.is_file()}
    if manifest.is_file():
        try:
            recorded = json.loads(manifest.read_text(encoding="utf-8"))
            mismatched = [
                relative for relative, digest in recorded.get("files", {}).items()
                if not (package_dir.parent / relative).is_file() or sha256_file(package_dir.parent / relative) != digest
            ]
            info["manifest_version"] = recorded.get("version")
            info["integrity"] = "ok" if not mismatched else f"modified: {', '.join(mismatched[:5])}"
        except (OSError, json.JSONDecodeError) as error:
            info["integrity"] = f"unreadable manifest: {error}"
    return info


def find_ui_ux_pro_max(repo_root: Path) -> str | None:
    """Where the optional ui-ux-pro-max design skill is installed (project first, then user-level), or None."""
    for skills_dir in (repo_root / ".claude" / "skills", Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"):
        if (skills_dir / "ui-ux-pro-max" / "SKILL.md").is_file():
            return str(skills_dir / "ui-ux-pro-max")
    return None


def collect_capabilities() -> dict[str, Any]:
    """Describe interpreter, platform, tools, network isolation and screenshot support (no network calls)."""
    tools = {}
    for name in OPTIONAL_TOOLS:
        path = shutil.which(name)
        tools[name] = {"path": path, "version": _tool_version(path) if path and name in ("git", "node", "docker", "uv") else None}
    sandbox_exec = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    playwright_spec = importlib.util.find_spec("playwright")
    playwright_version = None
    if playwright_spec:
        try:
            playwright_version = importlib.metadata.version("playwright")
        except importlib.metadata.PackageNotFoundError:
            playwright_version = "unknown"
    return {
        "devskills": __version__,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "meets_minimum": sys.version_info[:2] >= MIN_PYTHON,
            # sys._is_gil_enabled exists on 3.13+; the GIL is enabled on regular builds.
            "free_threaded_build": not getattr(sys, "_is_gil_enabled", lambda: True)(),
        },
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "tools": tools,
        "risky_profiles_require_os_isolation": True,
        "network_isolation": "os_sandbox_macos+python_socket_guard" if sandbox_exec else "python_socket_guard_only(partial)",
        "screenshots": {
            "playwright_python": playwright_version,
            "browsers_installed": _playwright_browsers(),
            "pillow": importlib.util.find_spec("PIL") is not None,
        },
        "runtime": _runtime_location(),
    }


def run(args: argparse.Namespace) -> int:
    """CLI handler for `doctor`; exit 4 when the interpreter is older than the supported minimum."""
    capabilities = collect_capabilities()
    repo_root = resolve_repo_root(args.repo)
    profile, _warnings = load_profile(repo_root)
    capabilities["code_graph"] = detect(repo_root, resolve_mode(None, profile)).to_dict()
    capabilities["ui_ux_pro_max"] = find_ui_ux_pro_max(repo_root)
    if args.json:
        print(json.dumps(capabilities, indent=2, ensure_ascii=False))
        return 0 if capabilities["python"]["meets_minimum"] else 4
    python = capabilities["python"]
    lines = [
        f"devskills {capabilities['devskills']} — Python {python['version']} ({python['executable']})"
        + ("" if python["meets_minimum"] else f"  [needs >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}]"),
        f"platform: {capabilities['platform']['system']} {capabilities['platform']['release']} {capabilities['platform']['machine']}",
        f"network isolation for run-tests: {capabilities['network_isolation']}",
    ]
    for name, info in capabilities["tools"].items():
        lines.append(f"  {name:7} {info['version'] or info['path'] or 'missing'}")
    screenshots = capabilities["screenshots"]
    if screenshots["playwright_python"] and screenshots["browsers_installed"]:
        lines.append(f"screenshots: ready (playwright {screenshots['playwright_python']}, {len(screenshots['browsers_installed'])} browser builds)")
    else:
        lines.append("screenshots: BLOCKED until `python3 -m pip install playwright` and `python3 -m playwright install chromium`")
    code_graph = capabilities["code_graph"]
    lines.append(f"codegraph (optional, mode {code_graph['mode']}): "
                 + (f"available, {code_graph['version']}, index at {code_graph['project_root']}" if code_graph["available"]
                    else code_graph["reason"]))
    lines.append("ui-ux-pro-max (optional UI design skill): " + (capabilities["ui_ux_pro_max"] or
                 "not installed — python3 agent-skills.py update --with-ui-ux-pro-max"))
    runtime = capabilities["runtime"]
    lines.append(f"runtime: {'vendored' if runtime['vendored'] else 'source checkout'} at {runtime['package_dir']}"
                 + (f" (integrity {runtime.get('integrity')})" if runtime["vendored"] else ""))
    print("\n".join(lines))
    return 0 if python["meets_minimum"] else 4
