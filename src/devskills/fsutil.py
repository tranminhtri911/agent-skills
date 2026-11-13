"""Filesystem and git helpers with the safety limits required by the plan.

Implemented rules: atomic writes (plan §24.7), artifacts confined to allowed
roots (RUN-003), secret files never read for context (AGENT-003) and bounded
reads so very large repositories cannot exhaust memory (PERF-007).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

# Directories that never contain first-party source worth scanning.
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".devskills", ".codegraph", ".knowledge", "node_modules", "bower_components", "vendor",
    "dist", "build", "out", "target", "obj", "coverage", "htmlcov",
    ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", ".next", ".nuxt", ".svelte-kit", ".angular", ".turbo", ".cache",
    ".gradle", ".idea", ".vscode", "Pods", "DerivedData", ".terraform", ".serverless",
})

# Files whose content is never read for context (AGENT-003). Env templates such
# as `.env.example` stay readable because they only document configuration keys.
SECRET_FILE_GLOBS = (
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".npmrc", ".pypirc", ".netrc", ".git-credentials", ".dockercfg",
    "credentials", "credentials.json", "service-account*.json", "*secret*.json", "secrets.y*ml",
)
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")

# Lockfiles hold integrity hashes and generated data; scanning them adds noise only.
LOCKFILE_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "poetry.lock", "uv.lock",
    "Pipfile.lock", "composer.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "packages.lock.json", "gradle.lockfile",
})

STATE_DIR_NAME = ".devskills"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

DEFAULT_MAX_TEXT_BYTES = 1024 * 1024


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a `Z` suffix and second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` atomically: temp file in the same directory, fsync, then replace.

    A crash or full disk never leaves a half-written report behind; the caller
    sees the exception and must report the artifact as missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass  # Already replaced or never created: nothing left to clean up.
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Hash a file in chunks so large artifacts do not load into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    """True when `path` resolves inside `root` (symlinks resolved)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_secret_file(rel_path: str) -> bool:
    """True for files that may hold credentials and must not be read for context."""
    name = PurePosixPath(rel_path.replace("\\", "/")).name.lower()
    if name.startswith(".env"):
        return not name.endswith(ENV_TEMPLATE_SUFFIXES)
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_FILE_GLOBS)


def is_lockfile(rel_path: str) -> bool:
    return PurePosixPath(rel_path).name in LOCKFILE_NAMES


def read_text_limited(path: Path, max_bytes: int = DEFAULT_MAX_TEXT_BYTES) -> str | None:
    """Read a UTF-8 text file; return None for binary, unreadable or oversized files."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def run_git(root: Path, args: list[str], timeout_seconds: float = 30) -> str | None:
    """Run a read-only git command; return stdout, or None when git is unavailable or fails."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace")


def resolve_repo_root(repo_argument: str | None) -> Path:
    """Resolve the repository root.

    An explicit `--repo PATH` is used as given (it may be a package inside a
    monorepo). Without it, the git top-level of the current directory is used,
    falling back to the current directory outside git.
    """
    if repo_argument:
        root = Path(repo_argument).expanduser().resolve()
        if not root.is_dir():
            from devskills.models import UsageError

            raise UsageError(f"repository path does not exist: {root}")
        return root
    current = Path.cwd()
    top_level = run_git(current, ["rev-parse", "--show-toplevel"])
    return Path(top_level.strip()).resolve() if top_level else current.resolve()


def git_prefix(root: Path) -> str | None:
    """Path of `root` inside its git work tree ('' at the top level, 'pkg/api/' below); None outside git."""
    prefix = run_git(root, ["rev-parse", "--show-prefix"])
    return prefix.strip() if prefix is not None else None


def git_status_entries(root: Path) -> list[dict[str, str]] | None:
    """Parse `git status --porcelain=v1 -z` for `root` only; return None when it is not in a git work tree.

    Porcelain paths are relative to the work-tree top level, so they are limited to
    `root` with a pathspec and re-based onto `root` (monorepo packages, nested folders).
    """
    prefix = git_prefix(root)
    if prefix is None:
        return None
    output = run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."])
    if output is None:
        return None
    entries: list[dict[str, str]] = []
    tokens = output.split("\0")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        code, path = token[:2], token[3:]
        if code[0] in "RC":
            # Renames and copies are followed by the original path, which is not needed here.
            index += 1
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        entries.append({"code": code, "path": path})
    return entries


def git_snapshot(root: Path) -> dict[str, Any]:
    """Describe the working tree so the agent can preserve uncommitted developer changes."""
    entries = git_status_entries(root)
    if entries is None:
        return {"is_repo": False}
    head = run_git(root, ["rev-parse", "HEAD"])
    branch = run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "is_repo": True,
        "branch": branch.strip() if branch else None,
        "head": head.strip() if head else None,
        "uncommitted": [entry for entry in entries if entry["code"] != "??"],
        "untracked": [entry["path"] for entry in entries if entry["code"] == "??"],
    }


def changed_files(root: Path, base: str | None = None) -> list[str]:
    """Paths changed in the working tree, plus commits since `base` when given."""
    paths: list[str] = []
    if base:
        # --relative limits the diff to `root` and prints paths relative to it.
        committed = run_git(root, ["diff", "--name-only", "-z", "--relative", f"{base}...HEAD"])
        if committed:
            paths.extend(path for path in committed.split("\0") if path)
    for entry in git_status_entries(root) or []:
        if entry["code"][1] != "D" and entry["code"][0] != "D":
            paths.append(entry["path"])
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(paths))


def working_state_digest(root: Path) -> str | None:
    """Fingerprint HEAD plus uncommitted changes so evidence ties to an exact state (plan §26.5)."""
    if run_git(root, ["rev-parse", "--is-inside-work-tree"]) is None:
        return None
    hasher = hashlib.sha256()
    head = (run_git(root, ["rev-parse", "HEAD"]) or "NO_HEAD").strip()
    hasher.update(head.encode())
    diff_args = (["diff", "--binary", "HEAD", "--", "."] if head != "NO_HEAD" else ["diff", "--binary", "--cached", "--", "."])
    try:
        # Stream the diff into the hash instead of capturing it, so huge diffs stay out of memory.
        process = subprocess.Popen(
            ["git", "-C", str(root), *diff_args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        if process.stdout is None:
            return None
        for chunk in iter(lambda: process.stdout.read(1 << 16), b""):
            hasher.update(chunk)
        process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        process.kill()
        return None
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    for entry in git_status_entries(root) or []:
        if entry["code"] != "??":
            continue
        untracked_path = root / entry["path"]
        hasher.update(entry["path"].encode())
        if untracked_path.is_file() and not untracked_path.is_symlink():
            hasher.update(sha256_file(untracked_path).encode())
    return hasher.hexdigest()


def current_repo_state(root: Path) -> dict[str, Any]:
    head = run_git(root, ["rev-parse", "HEAD"])
    return {"head": head.strip() if head else None, "diff_digest": working_state_digest(root)}


def _has_excluded_part(rel_path: str) -> bool:
    parts = PurePosixPath(rel_path.replace("\\", "/")).parts[:-1]
    return any(part in DEFAULT_EXCLUDED_DIRS for part in parts)


def _walk_files(root: Path) -> Iterator[str]:
    """Fallback listing outside git: prune excluded dirs and virtualenvs, skip symlinks."""
    for current_dir, dir_names, file_names in os.walk(root):
        current = Path(current_dir)
        dir_names[:] = sorted(
            name for name in dir_names
            if name not in DEFAULT_EXCLUDED_DIRS
            and not (current / name).is_symlink()
            and not (current / name / "pyvenv.cfg").exists()
        )
        for file_name in sorted(file_names):
            file_path = current / file_name
            if file_path.is_symlink():
                continue
            yield file_path.relative_to(root).as_posix()


def list_repo_files(root: Path, max_files: int = 20000) -> tuple[list[str], bool]:
    """List candidate files, honoring .gitignore when git is available.

    Returns (relative paths, truncated). Paths may name deleted tracked files;
    callers check existence before reading.
    """
    output = run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    candidates: Iterator[str] = (
        (path for path in output.split("\0") if path) if output is not None else _walk_files(root)
    )
    files: list[str] = []
    for rel_path in candidates:
        if _has_excluded_part(rel_path):
            continue
        files.append(rel_path)
        if len(files) >= max_files:
            return files, True
    return list(dict.fromkeys(files)), False


def select_target_files(
    root: Path,
    explicit_paths: list[str] | None,
    scope: str,
    base: str | None,
    max_files: int = 20000,
) -> list[str]:
    """Choose files for a check: explicit paths, changed files (default) or all files."""
    if explicit_paths:
        selected = []
        for raw_path in explicit_paths:
            candidate = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
            if not is_within(candidate, root):
                continue
            if candidate.is_dir():
                for rel_path in _walk_files(candidate):
                    selected.append((candidate / rel_path).relative_to(root.resolve()).as_posix())
            elif candidate.is_file():
                selected.append(candidate.relative_to(root.resolve()).as_posix())
        return list(dict.fromkeys(selected))
    if scope == "all":
        files, _ = list_repo_files(root, max_files)
        return files
    return [path for path in changed_files(root, base) if not _has_excluded_part(path)]


def ensure_state_dir(root: Path) -> Path:
    """Create `<repo>/.devskills/` with a self-ignoring .gitignore (run artifacts stay out of git)."""
    state_dir = root / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    gitignore = state_dir / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(gitignore, "# Created by devskills: run evidence stays local.\n*\n")
    return state_dir


def validate_run_id(run_id: str) -> str:
    """Reject run ids that could escape the runs directory."""
    if not _RUN_ID_PATTERN.match(run_id or ""):
        from devskills.models import UsageError

        raise UsageError(f"invalid run id: {run_id!r}")
    return run_id


def run_dir_for(root: Path, run_id: str) -> Path:
    return ensure_state_dir(root) / "runs" / validate_run_id(run_id)
