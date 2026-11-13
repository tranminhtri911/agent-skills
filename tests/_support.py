"""Shared helpers for the devskills test suite (stdlib unittest only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def make_temp_dir(test_case) -> Path:
    """Temporary directory removed when the test finishes."""
    directory = tempfile.TemporaryDirectory(prefix="devskills-test-")
    test_case.addCleanup(directory.cleanup)
    return Path(directory.name).resolve()


def write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return completed.stdout


def init_git_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "devskills test")
    git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str = "fixture") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def run_cli(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: float = 120,
            input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run `python -m devskills` in a subprocess with the source tree on PYTHONPATH."""
    child_env = {key: value for key, value in os.environ.items() if not key.startswith("DEVSKILLS_")}
    child_env.update(env or {})
    child_env["PYTHONPATH"] = str(SRC_DIR)
    return subprocess.run([sys.executable, "-m", "devskills", *args], cwd=cwd, env=child_env, capture_output=True,
                          text=True, timeout=timeout, input=input_text, check=False)


def run_cli_json(*args: str, **kwargs) -> tuple[int, dict]:
    completed = run_cli(*args, "--json", **kwargs)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"not JSON (exit {completed.returncode}):\n{completed.stdout}\n{completed.stderr}") from error
    return completed.returncode, payload


def fake_secret(prefix: str, length: int = 24) -> str:
    """Build credential-shaped test strings at runtime so this repository never contains real-looking keys."""
    return prefix + ("Ab3" * length)[:length]
