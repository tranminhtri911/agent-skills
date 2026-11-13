"""Optional integration with CodeGraph (github.com/colbymchenry/codegraph).

CodeGraph keeps a local, tree-sitter based symbol and call graph of a project in
`.codegraph/` and refreshes it automatically. When it is installed and the project
is indexed, `inspect` adds its exploration (symbols, call paths, blast radius) and
the tests affected by the working-tree changes to the context map.

One flag controls it, first match wins: CLI `--codegraph`, env `DEVSKILLS_CODEGRAPH`,
`.devskills.toml` `[integrations] codegraph`, default `auto`.
    auto  use it when the CLI is installed and the project is indexed
    on    expected: report a warning when it is missing
    off   never call it (e.g. client projects that must not run extra tools)
It never runs `codegraph init`: building an index writes `.codegraph/` and starts a
file watcher, which is the user's decision.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devskills.models import UsageError

MODES = ("auto", "on", "off")
INDEX_DIR = ".codegraph"
DB_NAME = "codegraph.db"
TIMEOUT_SECONDS = 90
MAX_OUTPUT_CHARS = 400_000
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass
class CodeGraph:
    """Detected CodeGraph state for one repository."""

    mode: str
    executable: str | None
    project_root: Path | None  # directory that holds .codegraph/ (may be above the repository root)
    version: str | None
    reason: str

    @property
    def available(self) -> bool:
        return self.mode != "off" and bool(self.executable and self.project_root)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "available": self.available,
            "reason": self.reason,
            "version": self.version,
            "project_root": str(self.project_root) if self.project_root else None,
        }


def resolve_mode(flag: str | None, profile: dict[str, Any]) -> str:
    """CLI flag > DEVSKILLS_CODEGRAPH > profile [integrations] codegraph > auto."""
    candidates = (flag, os.environ.get("DEVSKILLS_CODEGRAPH"), (profile.get("integrations") or {}).get("codegraph"))
    for value in candidates:
        if value:
            normalized = str(value).strip().lower()
            if normalized not in MODES:
                raise UsageError(f"codegraph mode must be one of {', '.join(MODES)} (got {value!r})")
            return normalized
    return "auto"


def find_index_root(start: Path) -> Path | None:
    """Nearest directory at or above `start` that holds a CodeGraph database (same rule as CodeGraph itself)."""
    for directory in (start, *start.parents):
        if (directory / INDEX_DIR / DB_NAME).is_file():
            return directory
    return None


def _run(executable: str, args: list[str], cwd: Path) -> str | None:
    """Run one read-only CodeGraph command; None when it fails, times out or is missing."""
    try:
        completed = subprocess.run([executable, *args], cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return _ANSI_ESCAPE.sub("", completed.stdout.decode("utf-8", errors="replace"))[:MAX_OUTPUT_CHARS]


def detect(repo_root: Path, mode: str) -> CodeGraph:
    """Find the CLI and the project index without running anything that writes."""
    if mode == "off":
        return CodeGraph(mode, None, None, None, "disabled (codegraph=off)")
    executable = shutil.which("codegraph")
    if executable is None:
        return CodeGraph(mode, None, None, None, "CodeGraph CLI not installed (optional: npm install -g @colbymchenry/codegraph)")
    version_output = _run(executable, ["--version"], repo_root)
    version = version_output.strip().splitlines()[0] if version_output and version_output.strip() else None
    project_root = find_index_root(repo_root)
    if project_root is None:
        return CodeGraph(mode, executable, None, version,
                         "project not indexed; the user may run `codegraph init` (never run automatically)")
    return CodeGraph(mode, executable, project_root, version, "available")


def _run_json(graph: CodeGraph, args: list[str]) -> Any | None:
    if not graph.available:
        return None
    output = _run(graph.executable, args, graph.project_root)
    if output is None:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def index_status(graph: CodeGraph) -> dict[str, Any] | None:
    """Index freshness and size: last indexed time, counts, pending changes, reindex hint."""
    data = _run_json(graph, ["status", str(graph.project_root), "--json"])
    if not isinstance(data, dict):
        return None
    pending = data.get("pendingChanges") or {}
    return {
        "last_indexed": data.get("lastIndexed"),
        "files": data.get("fileCount"),
        "symbols": data.get("nodeCount"),
        "edges": data.get("edgeCount"),
        "pending_changes": sum(value for value in pending.values() if isinstance(value, int)),
        "reindex_recommended": bool((data.get("index") or {}).get("reindexRecommended")),
        "worktree_mismatch": data.get("worktreeMismatch"),
    }


def explore(graph: CodeGraph, keywords: list[str], max_files: int = 8) -> str | None:
    """Symbols' source, call paths and blast radius for the keywords (Markdown)."""
    if not graph.available or not keywords:
        return None
    return _run(graph.executable, ["explore", "-p", str(graph.project_root), "--max-files", str(max_files), *keywords],
                graph.project_root)


def affected_tests(graph: CodeGraph, files: list[Path]) -> list[str] | None:
    """Test files that depend on the given source files, according to the graph."""
    if not graph.available or not files:
        return None
    data = _run_json(graph, ["affected", "-p", str(graph.project_root), "--json", *[str(path) for path in files]])
    if not isinstance(data, dict):
        return None
    return [str(path) for path in data.get("affectedTests") or []]
