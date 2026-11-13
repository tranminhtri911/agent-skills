"""Project knowledge index commands: init, build, check (index-project-knowledge skill).

`init` installs a self-contained `.knowledge/build.py` (copied from
knowledge_template.py) plus `config.json` into the project, so anyone can
rebuild or check the index later without this skill. The convention matches
existing projects: `.knowledge/INDEX.md`, `mirrors/`, `data/`, `manifest.json`,
and `python3 .knowledge/build.py --check` printing CURRENT or STALE.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

from devskills.fsutil import atomic_write_json, atomic_write_text, resolve_repo_root, utc_now_iso
from devskills.models import EXEC_COMPLETED, EXEC_TOOL_ERROR, GATE_BLOCKED, GATE_PASS, GATE_WARN, CheckResult, UsageError
from devskills.output import emit_result

TEMPLATE_PATH = Path(__file__).resolve().parent / "knowledge_template.py"
DOC_ROOT_CANDIDATES = ("docs", "doc", "specs", "spec", "plans", "requirements", "design", "adr", "ticket", "tickets", "wiki")
ROOT_FILES = ("README.md", "README.rst", "CLAUDE.md", "AGENTS.md", "GEMINI.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "CHANGELOG.md")


def discover_layout(root: Path) -> dict:
    """Find document roots at the top level and one level down (workspace with sub-projects)."""
    roots = [name for name in DOC_ROOT_CANDIDATES if (root / name).is_dir()]
    files = [name for name in ROOT_FILES if (root / name).is_file()]
    hidden_roots = [".claude/rules"] if (root / ".claude" / "rules").is_dir() else []
    for child in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        if child.name in ("node_modules", "vendor", "dist", "build") or child.name in roots:
            continue
        for file_name in ("CLAUDE.md", "AGENTS.md", "README.md"):
            if (child / file_name).is_file():
                files.append(f"{child.name}/{file_name}")
        for doc_dir in ("docs", "specs", "spec"):
            if (child / doc_dir).is_dir():
                roots.append(f"{child.name}/{doc_dir}")
        if (child / ".claude" / "rules").is_dir():
            hidden_roots.append(f"{child.name}/.claude/rules")
    return {"roots": roots, "files": files, "hidden_roots": hidden_roots}


def _has_pdf(root: Path, roots: list[str]) -> bool:
    return any(next((root / name).rglob("*.pdf"), None) is not None for name in roots if (root / name).is_dir())


def _run_script(root: Path, check_only: bool) -> tuple[int, str]:
    script = root / ".knowledge" / "build.py"
    if not script.is_file():
        return 4, "no .knowledge/build.py (run `knowledge init`)"
    arguments = [sys.executable, str(script)] + (["--check"] if check_only else [])
    try:
        completed = subprocess.run(arguments, cwd=root, capture_output=True, timeout=1800, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 4, "knowledge build timed out after 30 minutes"
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").strip()
    return completed.returncode, output


def cmd_init(args: argparse.Namespace, root: Path) -> int:
    """Create .knowledge/ (build.py, config.json, .gitignore, requirements.txt for PDFs), then build and check it."""
    knowledge_dir = root / ".knowledge"
    if (knowledge_dir / "INDEX.md").is_file() and not args.force:
        print(f"{knowledge_dir / 'INDEX.md'} already exists; use `knowledge check` (or --force to reinstall build.py/config)")
        return 0
    layout = discover_layout(root)
    if not layout["roots"] and not layout["files"]:
        raise UsageError("no document folders (docs/, specs/, plans/, ...) or guide files found; nothing to index yet")
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE_PATH, knowledge_dir / "build.py")
    config_path = knowledge_dir / "config.json"
    if not config_path.is_file() or args.force:
        template_config = {
            "format_version": 1,
            "title": args.title or f"{root.name} Knowledge Index",
            "language": args.language,
            **layout,
        }
        atomic_write_json(config_path, template_config)
    atomic_write_text(knowledge_dir / ".gitignore", "__pycache__/\n*.pyc\n.venv/\n")
    if _has_pdf(root, layout["roots"]):
        try:
            requirement = f"pypdf=={importlib.metadata.version('pypdf')}"
        except importlib.metadata.PackageNotFoundError:
            requirement = "pypdf>=5,<7"
        atomic_write_text(knowledge_dir / "requirements.txt",
                          "# Only PDF regeneration needs a third-party package; --check uses the standard library.\n" + requirement + "\n")
    print(f"initialised {knowledge_dir} (roots: {', '.join(layout['roots']) or '-'}; files: {', '.join(layout['files']) or '-'})")
    code, output = _run_script(root, check_only=False)
    print(output)
    if code == 0:
        code, output = _run_script(root, check_only=True)
        print(output)
    print("next: read the key documents and fill the knowledge:manual block in .knowledge/INDEX.md (reading order, sync rules)")
    return code


def run(args: argparse.Namespace) -> int:
    """CLI handler for `knowledge init|build|check`; `check` records CURRENT as pass and STALE as warn."""
    root = resolve_repo_root(args.repo)
    if args.knowledge_action == "init":
        return cmd_init(args, root)
    if args.knowledge_action == "build":
        code, output = _run_script(root, check_only=False)
        print(output)
        return code
    code, output = _run_script(root, check_only=True)
    if output.startswith("CURRENT"):
        gate, domain = GATE_PASS, "CURRENT"
    elif output.startswith("STALE"):
        gate, domain = GATE_WARN, "STALE"
    else:
        gate, domain = GATE_BLOCKED, "missing"
    result = CheckResult(
        check_id=getattr(args, "check_id", "docs.knowledge"),
        tool="devskills.knowledge",
        execution_status=EXEC_COMPLETED if domain != "missing" else EXEC_TOOL_ERROR,
        gate_result=gate,
        domain_result=domain,
        summary=output.splitlines()[0] if output else "",
        details={"output": output[:4000], "index": str(root / ".knowledge" / "INDEX.md")},
        started_at=utc_now_iso(),
    )
    if getattr(args, "json", False):
        return emit_result(args, root, result, [])
    return emit_result(args, root, result, [output])
