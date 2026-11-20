#!/usr/bin/env python3
"""Install, update, check, roll back and remove the devskills skill set (stdlib only).

    python3 agent-skills.py install  [--target claude-user|claude-project|agents|codex] [--skills a,b] [--link]
                                     [--with-venv [PATH]] [--extras ui,imaging,pdf,contracts|none]
                                     [--with-codegraph] [--with-ui-ux-pro-max --ui-ux-version X.Y.Z]   # opt-in UI tool
                                     [--without-agent-rules]   # skip the always-loaded rule in CLAUDE.md/AGENTS.md
                                     [--without-skill-gate]    # skip the skill-gate hooks (on by default)
    python3 agent-skills.py status   [--target ...]       # installed vs source, local edits, optional tools
    python3 agent-skills.py update   [--target ...] [--force] [--with-codegraph] [--without-ui-ux-pro-max]
    python3 agent-skills.py rollback [--target ...] [--backup TIMESTAMP]
    python3 agent-skills.py uninstall [--target ...] [--skills a,b] [--remove-venv]
    python3 agent-skills.py guard    [--target claude-user|claude-project] [--remove]  # remove legacy hooks/rules
    python3 agent-skills.py rules    [--project PATH] [--file claude|agents|both] [--remove]  # rule in a chosen project
    python3 agent-skills.py sync     # developers: copy tools/ds_shim.py into skills/*/scripts/ds.py

Every installed skill is self-contained: SKILL.md + references/assets + scripts/ds.py
+ a vendored copy of the runtime in scripts/_runtime (with a hash manifest).
Replaced or removed skills are backed up under ~/.devskills/backups/ first.

Skills load only when the agent decides a description matches, so install/update
also write a short always-loaded rule (tools/agent-rules.md) into the target's
instruction file (~/.claude/CLAUDE.md, <project>/CLAUDE.md, ~/.codex/AGENTS.md)
between devskills markers; uninstall removes it. --without-agent-rules skips it.
A rule is only advice, so install/update also add the skill gate (tools/skill-gate; --without-skill-gate
skips it). Claude targets get hooks that deny code edits until the routed skills were loaded with the Skill
tool and block a "Skills applied" list that names skills never loaded; the codex target gets one
non-blocking hook in ~/.codex/hooks.json that adds the code-style references when apply_patch edits code
(Codex asks you to trust it once in /hooks). uninstall removes it.

The runtime itself needs only the standard library, so no virtualenv is required.
Optionally, `--with-venv` gives the skills their own virtualenv (~/.devskills/venv):
it is created only if it does not exist yet, receives the optional features
(Playwright screenshots, Pillow, pypdf) at the versions pinned in
requirements-lock.txt, and its interpreter is recorded in each skill so ds.py runs
with it even inside a project whose own virtualenv is active. Later `update` runs
keep whichever interpreter the installed skills already use.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"devskills needs Python >= 3.11 (found {sys.version.split()[0]}); run the installer with a newer python3")

import tomllib  # noqa: E402  (3.11+, checked above)

REPO = Path(__file__).resolve().parent
SKILLS_SOURCE = REPO / "skills"
RUNTIME_SOURCE = REPO / "src" / "devskills"
SHIM_SOURCE = REPO / "tools" / "ds_shim.py"
SKILL_GATE_INSTALLER = REPO / "tools" / "skill-gate" / "install.py"
LOCK_FILE = REPO / "requirements-lock.txt"
MARKER_NAME = ".devskills-install.json"
BACKUP_ROOT = Path(os.environ.get("DEVSKILLS_BACKUP_DIR", Path.home() / ".devskills" / "backups"))
DEFAULT_VENV = Path(os.environ.get("DEVSKILLS_VENV", Path.home() / ".devskills" / "venv"))
DEFAULT_EXTRAS = "ui,imaging,pdf"
IGNORED_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache"}
CLAUDE_TARGETS = {"claude-user", "claude-project"}
PLACEHOLDER = "${CLAUDE_SKILL_DIR}"
GUARD_MARKER = "ds.py\" guard"
# Optional third-party tools require explicit installation.
CODEGRAPH_PACKAGE = "@colbymchenry/codegraph"
UIUX_PACKAGE = "ui-ux-pro-max-cli"
UIUX_SKILL = "ui-ux-pro-max"
# uipro `--ai` value and whether it installs globally (home) or into the project, per named target.
UIUX_TARGETS = {"claude-user": ("claude", True), "claude-project": ("claude", False),
                "agents": ("universal", True), "codex": ("codex", True)}
# Always-loaded rule that makes agents invoke dev-orchestrate; written between markers so updates
# replace only this block and uninstall removes it. The heading also matches a copy pasted by hand.
AGENT_RULES_SOURCE = REPO / "tools" / "agent-rules.md"
AGENT_RULES_BEGIN = "<!-- devskills:agent-rules begin — managed by agent-skills.py; edit tools/agent-rules.md in the source repo -->"
AGENT_RULES_END = "<!-- devskills:agent-rules end -->"
_AGENT_RULES_BLOCK = re.compile(r"<!-- devskills:agent-rules begin.*?<!-- devskills:agent-rules end -->\n?", re.DOTALL)
_AGENT_RULES_HAND_COPY = re.compile(r"^# Development skills \(devskills\)\n.*?(?=^# |\Z)", re.DOTALL | re.MULTILINE)

# Legacy rules retained only to remove settings written by older installers.
# Never install these blanket prompts: they also interrupt authorized local work.
ASK_RULES = [
    "Bash(git branch -d *)", "Bash(git branch -D *)", "Bash(git branch --delete *)", "Bash(git branch -m *)",
    "Bash(git branch -M *)", "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)",
    "Bash(git push * -f*)", "Bash(git push * --delete *)", "Bash(git push * :*)", "Bash(git push * main)",
    "Bash(git push * main *)", "Bash(git push * master)", "Bash(git push * master *)", "Bash(git reset --hard*)",
    "Bash(git clean -*f*)", "Bash(git checkout -- *)",
    "Bash(git restore *)", "Bash(git stash drop*)", "Bash(git stash clear*)", "Bash(git rebase *)",
    "Bash(git commit --amend*)", "Bash(git commit * --amend*)", "Bash(git filter-branch *)", "Bash(git filter-repo *)",
    "Bash(git tag -d *)", "Bash(git update-ref -d *)",
    "Bash(dropdb *)", "Bash(* migrate:fresh*)", "Bash(* migrate:reset*)", "Bash(* migrate:refresh*)",
    "Bash(* migrate:rollback*)", "Bash(* db:drop*)", "Bash(* db:reset*)", "Bash(* db:wipe*)",
    "Bash(* prisma migrate reset*)", "Bash(* manage.py flush*)", "Bash(docker compose down -v*)",
    "Bash(docker compose down --volumes*)", "Bash(docker-compose down -v*)", "Bash(docker volume rm *)",
    "Bash(docker volume prune*)", "Bash(redis-cli * FLUSHALL*)", "Bash(redis-cli FLUSHALL*)",
    "Bash(rm -rf *)", "Bash(rm -fr *)", "Bash(rm -r *)", "Bash(sudo *)", "Bash(chmod -R 777 *)",
    "Bash(terraform apply*)", "Bash(terraform destroy*)", "Bash(kubectl delete *)", "Bash(helm uninstall *)",
    "Bash(npm publish*)", "Bash(docker push *)",
    "Read(.env)", "Read(.env.local)", "Read(.env.production)", "Read(~/.ssh/**)", "Read(~/.aws/**)",
]
# Rules earlier versions installed that matched harmless commands (git clean -n, git push origin main-page);
# reinstalling or removing the guard deletes them.
RETIRED_ASK_RULES = ["Bash(git clean *)", "Bash(git push * main*)", "Bash(git push * master*)"]


class InstallError(Exception):
    """A problem the user must fix; reported without a traceback."""


# --------------------------------------------------------------------------- helpers


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    """sha256 of every file under root (marker excluded), keyed by POSIX relative path."""
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != MARKER_NAME and not set(path.relative_to(root).parts) & IGNORED_NAMES:
            hashes[path.relative_to(root).as_posix()] = sha256_file(path)
    return hashes


def tree_digest(hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def runtime_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', (RUNTIME_SOURCE / "__init__.py").read_text(encoding="utf-8"))
    return match.group(1) if match else "unknown"


def source_skill_names() -> list[str]:
    return sorted(path.parent.name for path in SKILLS_SOURCE.glob("*/SKILL.md"))


def resolve_target(args: argparse.Namespace) -> tuple[Path, bool]:
    """Return (skills directory, keep ${CLAUDE_SKILL_DIR} placeholders)."""
    if args.target_dir:
        return Path(args.target_dir).expanduser().resolve(), not args.render_paths
    target = args.target
    if target == "claude-user":
        return Path.home() / ".claude" / "skills", True
    if target == "claude-project":
        return Path(args.project or os.getcwd()).resolve() / ".claude" / "skills", True
    if target == "agents":
        return Path.home() / ".agents" / "skills", False
    if target == "codex":
        return Path.home() / ".codex" / "skills", False
    raise InstallError(f"unknown target {target!r}")


def warn_shared_skill_names(args: argparse.Namespace, target_root: Path, names: list[str], *, creating: bool = False) -> None:
    """Flag copies in both user directories visible to a Codex session."""
    if args.target_dir or args.target not in {"agents", "codex"}:
        return
    other_target = ".agents" if args.target == "codex" else ".codex"
    other_root = Path.home() / other_target / "skills"
    overlap = [name for name in names if (other_root / name / "SKILL.md").is_file()
               and (creating or (target_root / name / "SKILL.md").is_file())]
    if overlap:
        print(f"  warning: Codex may see the same skill names in {target_root} and {other_root}:")
        print(f"    {', '.join(overlap)}")
        print("    Use one of these directories for devskills visible to Codex.")


def selected_skills(args: argparse.Namespace) -> list[str]:
    available = source_skill_names()
    if not args.skills:
        return available
    requested = [name.strip() for name in args.skills.split(",") if name.strip()]
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise InstallError(f"unknown skills: {', '.join(unknown)} (available: {', '.join(available)})")
    return requested


def backup_dir_for(target_root: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(target_root)).strip("_")[-80:]
    return BACKUP_ROOT / slug


def read_marker(skill_dir: Path) -> dict | None:
    marker = skill_dir / MARKER_NAME
    if skill_dir.is_symlink() or not marker.is_file():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_linked_install(skill_dir: Path) -> bool:
    return skill_dir.is_symlink() and REPO in skill_dir.resolve().parents


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns(*IGNORED_NAMES))


def venv_python(venv_dir: Path) -> Path | None:
    for candidate in (venv_dir / "bin" / "python", venv_dir / "Scripts" / "python.exe"):
        if candidate.is_file():
            return candidate
    return None


def parse_extras(text: str) -> list[str]:
    """Validate `--extras` against pyproject.toml's optional dependencies ('none' = no extras)."""
    if text.strip().lower() in ("", "none"):
        return []
    available = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    extras = [item.strip() for item in text.split(",") if item.strip()]
    unknown = sorted(set(extras) - set(available) - {"dev"})
    if unknown or "dev" in extras:
        raise InstallError(f"unknown extras: {', '.join(unknown or ['dev'])} (choose from {', '.join(sorted(set(available) - {'dev'}))})")
    return extras


def ensure_skills_venv(venv_dir: Path, extras: list[str], dry_run: bool) -> tuple[Path, bool]:
    """Create the skills' virtualenv only if it does not exist yet, then install the extras.

    Returns (venv python, extras installed successfully). Versions come from
    requirements-lock.txt, the set the test suite was run with.
    """
    python = venv_python(venv_dir)
    if python is None:
        print(f"venv: creating {venv_dir}{'  (dry run)' if dry_run else ''}")
        if dry_run:
            return venv_dir / "bin" / "python", True
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        python = venv_python(venv_dir)
        if python is None:
            raise InstallError(f"virtualenv created at {venv_dir} but no interpreter found inside it")
    else:
        print(f"venv: using existing {venv_dir}")
    if not extras or dry_run:
        if extras:
            print(f"venv: would install extras {', '.join(extras)}")
        return python, True
    optional = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    requirements = [requirement for extra in extras for requirement in optional[extra]]
    print(f"venv: installing {', '.join(requirements)} (pinned by {LOCK_FILE.name})")
    steps = [[str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
             [str(python), "-m", "pip", "install", "--quiet", *requirements, "-c", str(LOCK_FILE)]]
    if "ui" in extras:
        steps.append([str(python), "-m", "playwright", "install", "chromium"])
    for step in steps:
        if subprocess.run(step, check=False).returncode != 0:
            print(f"venv: WARNING `{' '.join(step[1:5])} …` failed (offline?). Skills still work; optional features "
                  "report BLOCKED until you rerun the install.")
            return python, False
    return python, True


def runtime_python_of(marker: dict | None) -> str:
    """Interpreter an existing install recorded, if it still exists; otherwise the current one."""
    recorded = (marker or {}).get("python")
    return recorded if recorded and Path(recorded).is_file() else sys.executable


def build_skill(name: str, staging: Path, final_path: Path, keep_placeholders: bool, python_path: str) -> dict:
    """Assemble a self-contained skill in `staging` and return its install marker."""
    copy_tree(SKILLS_SOURCE / name, staging)
    scripts = staging / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copyfile(SHIM_SOURCE, scripts / "ds.py")
    (scripts / "ds.py").chmod(0o755)
    runtime_root = scripts / "_runtime"
    copy_tree(RUNTIME_SOURCE, runtime_root / "devskills")
    runtime_files = tree_hashes(runtime_root)
    (runtime_root / "MANIFEST.json").write_text(json.dumps({"version": runtime_version(), "files": runtime_files}, indent=2) + "\n",
                                                encoding="utf-8")
    # ds.py re-launches itself with this interpreter (the skills' venv), whatever venv the project has active.
    (runtime_root / "PYTHON").write_text(python_path + "\n", encoding="utf-8")
    if not keep_placeholders:
        # Hosts other than Claude Code do not expand ${CLAUDE_SKILL_DIR}: write the real path.
        for document in [staging / "SKILL.md", *sorted((staging / "references").glob("*.md"))]:
            if document.is_file():
                text = document.read_text(encoding="utf-8")
                document.write_text(text.replace(PLACEHOLDER, str(final_path)), encoding="utf-8")
    files = tree_hashes(staging)
    marker = {
        "installer": "devskills agent-skills.py",
        "version": runtime_version(),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(REPO),
        "python": python_path,
        "placeholders_rendered": not keep_placeholders,
        "tree_digest": tree_digest(files),
        "files": files,
    }
    (staging / MARKER_NAME).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return marker


def local_changes(skill_dir: Path, marker: dict) -> list[str]:
    """Files edited, added or deleted by hand since installation."""
    recorded = marker.get("files", {})
    current = tree_hashes(skill_dir)
    changed = [path for path, digest in current.items() if recorded.get(path) != digest]
    removed = [path for path in recorded if path not in current]
    return sorted(changed + [f"{path} (deleted)" for path in removed])


def backup_skill(skill_dir: Path, target_root: Path, stamp: str, reason: str) -> Path:
    destination = backup_dir_for(target_root) / stamp / skill_dir.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if skill_dir.is_symlink():
        destination.parent.joinpath(f"{skill_dir.name}.symlink").write_text(os.readlink(skill_dir) + "\n", encoding="utf-8")
    else:
        copy_tree(skill_dir, destination)
    info_file = destination.parent / "BACKUP.json"
    info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.is_file() else {"target": str(target_root), "skills": {}}
    info["skills"][skill_dir.name] = reason
    info_file.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return destination


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def staged_marker(name: str, target_root: Path, keep_placeholders: bool, python_path: str) -> dict:
    """Marker the source would produce now (used for status/update comparisons)."""
    with tempfile.TemporaryDirectory(prefix="devskills-stage-") as temp:
        return build_skill(name, Path(temp) / name, target_root / name, keep_placeholders, python_path)


def verify_installation(target_root: Path, names: list[str]) -> bool:
    """Run the installed runtime: version check plus SKILL.md validation."""
    if not names:
        return True
    shim = target_root / names[0] / "scripts" / "ds.py"
    version = subprocess.run([sys.executable, str(shim), "--version"], capture_output=True, text=True, check=False)
    validation = subprocess.run([sys.executable, str(shim), "validate-skills", *[str(target_root / name) for name in names]],
                                capture_output=True, text=True, check=False)
    print(f"verify: {version.stdout.strip() or version.stderr.strip()}")
    if validation.returncode != 0:
        print(validation.stdout + validation.stderr)
        return False
    print(f"verify: {len(names)} skill(s) valid")
    return version.returncode == 0


# --------------------------------------------------------------------------- commands


def instructions_file_for(args: argparse.Namespace) -> Path | None:
    """The always-loaded instruction file of a named target, or None when the target has no such file."""
    if args.target_dir:
        return None
    if args.target == "claude-user":
        return Path.home() / ".claude" / "CLAUDE.md"
    if args.target == "claude-project":
        return Path(args.project or os.getcwd()).resolve() / "CLAUDE.md"
    if args.target == "codex":
        return Path.home() / ".codex" / "AGENTS.md"
    return None


def agent_rules_block() -> str:
    return f"{AGENT_RULES_BEGIN}\n{AGENT_RULES_SOURCE.read_text(encoding='utf-8').strip()}\n{AGENT_RULES_END}\n"


def with_agent_rules(text: str, block: str | None) -> str:
    """Return `text` with the managed block replaced, added (block given) or removed (block None).

    A hand-pasted copy (same heading, no markers) is replaced in place instead of duplicated.
    """
    match = _AGENT_RULES_BLOCK.search(text) or _AGENT_RULES_HAND_COPY.search(text)
    if match:
        before, rest = text[:match.start()], text[match.end():].lstrip("\n")
        updated = before + (block + ("\n" + rest if rest else "") if block else rest)
    elif block is None:
        return text
    else:
        updated = text.rstrip("\n") + ("\n\n" if text.strip() else "") + block
    if block is None:
        updated = re.sub(r"\n{3,}", "\n\n", updated).rstrip("\n") + ("\n" if updated.strip() else "")
    return updated


def apply_agent_rules(args: argparse.Namespace, remove: bool = False) -> bool:
    """Write (or remove) the always-loaded rule in the target's instruction file."""
    path = instructions_file_for(args)
    if path is None:
        if not remove:
            print("  agent rules: this target has no always-loaded instruction file — run "
                  "`python3 agent-skills.py rules --project <path>` or add tools/agent-rules.md to the agent's instructions")
        return True
    return write_agent_rules(path, args.dry_run, remove)


def write_agent_rules(path: Path, dry_run: bool, remove: bool = False) -> bool:
    """Write (or remove) the managed rule block in one instruction file; back the file up first."""
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = with_agent_rules(current, None if remove else agent_rules_block())
    if updated == current:
        if not remove:
            print(f"  agent rules: up to date in {path}")
        return True
    action = "remove from" if remove else ("update in" if _AGENT_RULES_BLOCK.search(current)
                                           or _AGENT_RULES_HAND_COPY.search(current) else "add to")
    print(f"  agent rules: {action} {path}{'  (dry run)' if dry_run else ''}")
    if dry_run:
        return True
    if path.is_file():
        # Kept apart from the skill backups so `rollback` (which restores skill folders) is unaffected.
        backup = BACKUP_ROOT / "agent-rules" / f"{now_stamp()}-{re.sub(r'[^A-Za-z0-9]+', '_', str(path)).strip('_')[-80:]}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, backup)
        print(f"    backup: {backup}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.devskills-tmp")
    temp_path.write_text(updated, encoding="utf-8")
    os.replace(temp_path, path)
    return True


def apply_skill_gate(args: argparse.Namespace, remove: bool = False) -> bool:
    """Install (or remove) the skill-gate hooks in ~/.claude; returns False when that failed.

    The hooks force Claude Code to load dev-orchestrate and the routed domain skills before it edits
    code (tools/skill-gate). They are Claude Code settings scoped to the chosen user/project. The codex target
    gets one non-blocking style hook in ~/.codex/hooks.json; agents and --target-dir are left untouched.
    """
    if args.target not in CLAUDE_TARGETS | {"codex"} or args.target_dir:
        return True
    spec = importlib.util.spec_from_file_location("skill_gate_install", SKILL_GATE_INSTALLER)
    if spec is None or spec.loader is None:
        print(f"  skill gate: cannot load {SKILL_GATE_INSTALLER}")
        return False
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        if args.target == "codex":
            module.apply_codex(install=not remove, dry_run=args.dry_run, codex_dir=str(Path.home() / ".codex"))
            return True
        gate_dir = (Path(args.project or os.getcwd()).resolve() / ".claude"
                    if args.target == "claude-project" else Path.home() / ".claude")
        module.apply(install=not remove, dry_run=args.dry_run, claude_dir=str(gate_dir))
    except RuntimeError as exc:
        print(f"  skill gate: {exc}")
        return False
    return True


def install_or_update(args: argparse.Namespace, update_only: bool) -> int:
    target_root, keep_placeholders = resolve_target(args)
    if args.with_ui_ux_pro_max and not args.without_ui_ux_pro_max:
        if not args.ui_ux_version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.ui_ux_version):
            raise InstallError("--with-ui-ux-pro-max requires --ui-ux-version X.Y.Z (review that release first)")
    names = selected_skills(args)
    stamp = now_stamp()
    print(f"target: {target_root}{'  (dry run)' if args.dry_run else ''}")
    warn_shared_skill_names(args, target_root, names, creating=not update_only or args.link)
    if not args.dry_run:
        target_root.mkdir(parents=True, exist_ok=True)
    problems = 0
    # The virtualenv is optional. Without --with-venv each skill keeps the interpreter it already
    # records (an earlier venv stays in use) or, for a first install, the one running this script.
    venv_runtime: str | None = None
    if args.with_venv and not args.link:
        venv_path, extras_ok = ensure_skills_venv(Path(args.with_venv).expanduser(), parse_extras(args.extras), args.dry_run)
        venv_runtime = str(venv_path)
        problems += 0 if extras_ok else 1
    installed: list[str] = []
    for name in names:
        destination = target_root / name
        if args.link:
            if destination.exists() or destination.is_symlink():
                if not is_linked_install(destination):
                    marker = read_marker(destination)
                    if marker is None and not args.force:
                        print(f"  skip {name}: an existing skill with this name was not installed by devskills (use --force to back it up and replace)")
                        problems += 1
                        continue
                if not args.dry_run:
                    backup_skill(destination, target_root, stamp, "replaced by --link install")
                    remove_path(destination)
            print(f"  link {name} -> {SKILLS_SOURCE / name}")
            if not args.dry_run:
                destination.symlink_to(SKILLS_SOURCE / name, target_is_directory=True)
                installed.append(name)
            continue

        marker = read_marker(destination)
        runtime_python = venv_runtime or runtime_python_of(marker)
        exists = destination.exists() or destination.is_symlink()
        if update_only and not exists:
            print(f"  skip {name}: not installed (use `install`)")
            continue
        if exists and marker is None and not is_linked_install(destination) and not args.force:
            print(f"  skip {name}: {destination} exists but was not installed by devskills (use --force to back it up and replace)")
            problems += 1
            continue
        if marker is not None:
            edits = local_changes(destination, marker)
            if edits and not args.force:
                print(f"  skip {name}: {len(edits)} file(s) edited by hand since install: {', '.join(edits[:5])}"
                      f"{' …' if len(edits) > 5 else ''} — keep them in the source repo, or rerun with --force (a backup is kept)")
                problems += 1
                continue
            fresh = staged_marker(name, target_root, keep_placeholders, runtime_python)
            if fresh["tree_digest"] == marker.get("tree_digest") and not args.force:
                print(f"  ok   {name}: up to date ({marker.get('version')})")
                continue
            changed = sorted(set(fresh["files"].items()) ^ set(marker.get("files", {}).items()))
            print(f"  update {name}: {marker.get('version')} -> {fresh['version']} ({len({path for path, _ in changed})} file(s) differ)")
        else:
            print(f"  install {name}")
        if args.dry_run:
            continue
        staging = Path(tempfile.mkdtemp(prefix=f".{name}.staging-", dir=target_root))
        try:
            shutil.rmtree(staging)
            build_skill(name, staging, destination, keep_placeholders, runtime_python)
            if exists:
                backup_skill(destination, target_root, stamp, "replaced by install/update")
                remove_path(destination)
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        installed.append(name)
    if installed and not args.dry_run:
        print(f"backups (if any): {backup_dir_for(target_root) / stamp}")
        if not verify_installation(target_root, installed):
            return 1
        if args.target in CLAUDE_TARGETS and not args.target_dir:
            print("Claude Code picks up skill changes live; run /reload-skills if the skills directory was just created.")
    # The rule points at dev-orchestrate, so it is written only when that skill is part of this install.
    if not args.without_agent_rules and "dev-orchestrate" in names:
        apply_agent_rules(args)
    # On by default (--without-skill-gate opts out). Same condition as the rule: the gate's routing is
    # dev-orchestrate's, so it needs that skill installed.
    if not args.without_skill_gate and "dev-orchestrate" in names and not apply_skill_gate(args):
        problems += 1
    with_uiux = args.with_ui_ux_pro_max and not args.without_ui_ux_pro_max
    if args.with_codegraph or with_uiux:
        print("tools (explicit opt-in):")
    if args.with_codegraph and not install_codegraph(args.dry_run):
        problems += 1
    if with_uiux and not install_ui_ux_pro_max(args, target_root, stamp):
        problems += 1
    return 1 if problems else 0


def run_tool_install(label: str, argv: list[str], cwd: Path, dry_run: bool) -> bool:
    """Run an opt-in third-party install command as the current user (never sudo); report, never hide, failures."""
    print(f"  {label}: {' '.join(argv)}{'  (dry run)' if dry_run else ''}")
    if dry_run:
        return True
    try:
        completed = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"    failed: {error}")
        return False
    if completed.returncode != 0:
        print(f"    failed with exit code {completed.returncode}")
    return completed.returncode == 0


def install_codegraph(dry_run: bool) -> bool:
    """`npm install -g @colbymchenry/codegraph@latest`; projects still opt in with `codegraph init` themselves."""
    npm = shutil.which("npm")
    if not npm:
        print(f"  codegraph: npm not found — install Node.js, then npm install -g {CODEGRAPH_PACKAGE}@latest")
        return False
    if not run_tool_install("codegraph (latest)", [npm, "install", "-g", f"{CODEGRAPH_PACKAGE}@latest"], Path.home(), dry_run):
        print("    if npm needs root here, fix the npm prefix (or use nvm) instead of sudo")
        return False
    if not dry_run:
        print(f"    {tool_version('codegraph') or 'codegraph'} installed; the skills never index a project — "
              "run `codegraph init` in a project to enable it")
    return True


def install_ui_ux_pro_max(args: argparse.Namespace, target_root: Path, stamp: str) -> bool:
    """Install/refresh the ui-ux-pro-max skill with an explicitly selected CLI release.

    An existing copy is backed up first, like our own skills, so `rollback` can restore it.
    """
    if args.target_dir or args.target not in UIUX_TARGETS:
        print(f"  ui-ux-pro-max: no uipro mapping for --target-dir; run `npx -y {UIUX_PACKAGE}@latest init --ai <assistant>` there")
        return False
    npx = shutil.which("npx")
    if not npx:
        print(f"  ui-ux-pro-max: npx not found — install Node.js, then npx -y {UIUX_PACKAGE}@latest init --ai claude --global")
        return False
    ai_name, is_global = UIUX_TARGETS[args.target]
    existing = target_root / UIUX_SKILL
    if existing.exists() and not args.force:
        print("    ui-ux-pro-max already exists; use --force to replace it with a backup")
        return False
    if existing.exists() and not args.dry_run:
        backup_skill(existing, target_root, stamp, "replaced by explicitly selected ui-ux-pro-max release")
    argv = [npx, "-y", "--registry=https://registry.npmjs.org", f"{UIUX_PACKAGE}@{args.ui_ux_version}",
            "init", "--ai", ai_name, *(["--force"] if args.force else []), *(["--global"] if is_global else [])]
    # Project installs run from the project root (target_root is <project>/.claude/skills).
    if not run_tool_install("ui-ux-pro-max (explicit version)", argv, Path.home() if is_global else target_root.parent.parent, args.dry_run):
        return False
    if not args.dry_run and not (existing / "SKILL.md").is_file():
        print(f"    note: uipro placed the skill in its own folder for --ai {ai_name}, not in {target_root}")
    return True


def tool_version(command: str) -> str | None:
    """`<command> --version` of an optional tool, or None."""
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        completed = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip().splitlines()[0] if completed.returncode == 0 and completed.stdout.strip() else None


def cmd_status(args: argparse.Namespace) -> int:
    target_root, keep_placeholders = resolve_target(args)
    print(f"target: {target_root}  (source {REPO}, version {runtime_version()})")
    names = selected_skills(args)
    warn_shared_skill_names(args, target_root, names)
    outdated = 0
    for name in names:
        destination = target_root / name
        if is_linked_install(destination):
            print(f"  linked     {name} -> {destination.resolve()} (always current)")
            continue
        if not destination.exists():
            print(f"  missing    {name}")
            outdated += 1
            continue
        marker = read_marker(destination)
        if marker is None:
            print(f"  foreign    {name}: exists but not installed by devskills")
            continue
        edits = local_changes(destination, marker)
        fresh = staged_marker(name, target_root, keep_placeholders, runtime_python_of(marker))
        state = "up-to-date" if fresh["tree_digest"] == marker.get("tree_digest") else "outdated"
        outdated += state == "outdated"
        note = f"; {len(edits)} local edit(s): {', '.join(edits[:3])}" if edits else ""
        print(f"  {state:10} {name} (installed {marker.get('version')} at {marker.get('installed_at')}){note}")
    backups = sorted(path.name for path in backup_dir_for(target_root).glob("*") if path.is_dir()) if backup_dir_for(target_root).is_dir() else []
    if backups:
        print(f"backups: {', '.join(backups[-5:])} (rollback restores the latest unless --backup is given)")
    skills_venv = venv_python(DEFAULT_VENV)
    print(f"skills venv (optional): {skills_venv or 'not created — add --with-venv to install/update if you want one'}")
    codegraph_version = tool_version("codegraph")
    print(f"codegraph (optional call graph): "
          f"{codegraph_version or 'not installed'} — install/refresh to latest with `update --with-codegraph`")
    rules_path = instructions_file_for(args)
    if rules_path is not None:
        rules_text = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
        rules_state = ("up-to-date" if agent_rules_block() in rules_text
                       else "outdated" if _AGENT_RULES_BLOCK.search(rules_text) or _AGENT_RULES_HAND_COPY.search(rules_text)
                       else "missing")
        print(f"agent rules (always-loaded, makes agents use dev-orchestrate): {rules_state} in {rules_path}"
              + ("" if rules_state == "up-to-date" else " — `update` writes it"))
    uiux_state = "installed" if (target_root / UIUX_SKILL / "SKILL.md").is_file() else "not installed"
    print(f"ui-ux-pro-max (UI design reference, opt-in): {uiux_state} — use --with-ui-ux-pro-max --ui-ux-version X.Y.Z")
    return 1 if outdated else 0


def cmd_rollback(args: argparse.Namespace) -> int:
    target_root, _ = resolve_target(args)
    root = backup_dir_for(target_root)
    backups = sorted(path for path in root.glob("*") if path.is_dir()) if root.is_dir() else []
    if args.backup:
        backups = [path for path in backups if path.name == args.backup]
    if not backups:
        raise InstallError(f"no backup found under {root}")
    chosen = backups[-1]
    stamp = now_stamp()
    names = [path.name for path in chosen.iterdir() if path.is_dir()]
    links = [path for path in chosen.glob("*.symlink")]
    print(f"rollback from {chosen}{'  (dry run)' if args.dry_run else ''}")
    for name in sorted(names):
        destination = target_root / name
        print(f"  restore {name}")
        if args.dry_run:
            continue
        if destination.exists() or destination.is_symlink():
            backup_skill(destination, target_root, stamp, "replaced by rollback")
            remove_path(destination)
        copy_tree(chosen / name, destination)
    for link_file in links:
        destination = target_root / link_file.stem
        print(f"  restore link {link_file.stem}")
        if not args.dry_run:
            if destination.exists() or destination.is_symlink():
                backup_skill(destination, target_root, stamp, "replaced by rollback")
                remove_path(destination)
            destination.symlink_to(link_file.read_text(encoding="utf-8").strip(), target_is_directory=True)
    if not args.dry_run:
        print(f"the replaced version is backed up as {stamp}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    target_root, _ = resolve_target(args)
    stamp = now_stamp()
    for name in selected_skills(args):
        destination = target_root / name
        if not (destination.exists() or destination.is_symlink()):
            continue
        if read_marker(destination) is None and not is_linked_install(destination):
            print(f"  keep {name}: not installed by devskills")
            continue
        print(f"  remove {name}")
        if not args.dry_run:
            backup_skill(destination, target_root, stamp, "uninstall")
            remove_path(destination)
    if not args.dry_run:
        print(f"backup: {backup_dir_for(target_root) / stamp} (python3 agent-skills.py rollback restores it)")
    if "dev-orchestrate" in selected_skills(args):
        apply_agent_rules(args, remove=True)
        apply_skill_gate(args, remove=True)
    if (target_root / UIUX_SKILL).exists():
        print(f"  kept {UIUX_SKILL}: installed by its own CLI; delete {target_root / UIUX_SKILL} yourself if you no longer want it")
    if args.remove_venv:
        venv_dir = Path(args.venv).expanduser()
        # Only a directory that really is a virtualenv is removed; it can be recreated by `install`.
        if (venv_dir / "pyvenv.cfg").is_file():
            print(f"  remove venv {venv_dir}")
            if not args.dry_run:
                shutil.rmtree(venv_dir)
        else:
            print(f"  no virtualenv at {venv_dir}")
    return 0


RULES_FILES = {"claude": ("CLAUDE.md",), "agents": ("AGENTS.md",), "both": ("CLAUDE.md", "AGENTS.md")}


def cmd_rules(args: argparse.Namespace) -> int:
    """Write, refresh or remove the always-loaded rule in a chosen project's CLAUDE.md and/or AGENTS.md.

    Claude Code reads CLAUDE.md; Codex, Copilot, Cursor and most other agents read AGENTS.md.
    """
    project = Path(args.project or os.getcwd()).expanduser().resolve()
    if not project.is_dir():
        raise InstallError(f"project directory not found: {project}")
    print(f"project: {project}{'  (dry run)' if args.dry_run else ''}")
    for file_name in RULES_FILES[args.file]:
        write_agent_rules(project / file_name, args.dry_run, remove=args.remove)
    return 0


def cmd_sync(_args: argparse.Namespace) -> int:
    """Copy the canonical shim into every source skill (developer command)."""
    for name in source_skill_names():
        scripts = SKILLS_SOURCE / name / "scripts"
        scripts.mkdir(exist_ok=True)
        shutil.copyfile(SHIM_SOURCE, scripts / "ds.py")
        (scripts / "ds.py").chmod(0o755)
    print(f"synced tools/ds_shim.py into {len(source_skill_names())} skills")
    return 0


def settings_path_for(args: argparse.Namespace) -> Path:
    if args.settings:
        return Path(args.settings).expanduser().resolve()
    if args.target == "claude-user":
        return Path.home() / ".claude" / "settings.json"
    if args.target == "claude-project":
        project = Path(args.project or os.getcwd()).resolve()
        return project / ".claude" / ("settings.local.json" if args.local else "settings.json")
    raise InstallError("the guard hook is a Claude Code feature: use --target claude-user or claude-project")


def cmd_guard(args: argparse.Namespace) -> int:
    """Remove legacy devskills hooks/rules, preserving unrelated settings and hooks."""
    settings_path = settings_path_for(args)
    if not settings_path.is_file():
        print(f"no legacy devskills guard settings at {settings_path}")
        return 0
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as error:
            raise InstallError(f"{settings_path} is not valid JSON ({error}); fix it first, nothing was changed") from error
    original = json.loads(json.dumps(settings))
    hooks = settings.setdefault("hooks", {})
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    kept = []
    for entry in pre_tool_use:
        entry_hooks = entry.get("hooks", [])
        remaining = [hook for hook in entry_hooks
                     if not (GUARD_MARKER in hook.get("command", "") or "ds.py guard" in hook.get("command", ""))]
        if remaining == entry_hooks:
            kept.append(entry)
        elif remaining:
            kept.append({**entry, "hooks": remaining})
    permissions = settings.setdefault("permissions", {})
    ask_rules = [rule for rule in permissions.get("ask", []) if rule not in ASK_RULES and rule not in RETIRED_ASK_RULES]
    hooks["PreToolUse"] = kept
    permissions["ask"] = ask_rules
    action = "removed devskills guard hook and ask rules"
    for key in ("PreToolUse",):
        if not hooks.get(key):
            hooks.pop(key, None)
    if not hooks:
        settings.pop("hooks", None)
    if not permissions.get("ask"):
        permissions.pop("ask", None)
    if not permissions:
        settings.pop("permissions", None)
    if args.dry_run:
        print(f"(dry run) {action} in {settings_path}:\n{json.dumps(settings, indent=2)}")
        return 0
    if settings == original:
        print(f"no legacy devskills guard settings in {settings_path}")
        return 0
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.is_file():
        backup = settings_path.with_name(f"{settings_path.name}.devskills-backup-{now_stamp()}")
        shutil.copyfile(settings_path, backup)
        print(f"backup: {backup}")
    temp_path = settings_path.with_name(f".{settings_path.name}.tmp")
    temp_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp_path, settings_path)
    print(f"{action} in {settings_path}")
    return 0


# (summary, examples) per command, shown by `--help`, `<command> --help` and `help [command]`.
COMMAND_HELP = {
    "install": ("install the skills and the skill gate (UI reference, venv and CodeGraph are opt-in)", """\
examples:
  python3 agent-skills.py install                                   # all 20 skills into ~/.claude/skills
  python3 agent-skills.py install --dry-run                         # show what would happen, change nothing
  python3 agent-skills.py install --skills dev-orchestrate,test-safely
  python3 agent-skills.py install --target claude-project --project ~/work/shop
  python3 agent-skills.py install --with-venv                       # screenshots, image diff, PDF in ~/.devskills/venv
  python3 agent-skills.py install --with-codegraph                  # also CodeGraph, latest release
  python3 agent-skills.py install --with-ui-ux-pro-max --ui-ux-version X.Y.Z  # reviewed UI CLI release
  python3 agent-skills.py install --without-agent-rules             # do not add the devskills rule to CLAUDE.md
  python3 agent-skills.py install --without-skill-gate               # skills and rule only, no hooks
  python3 agent-skills.py install --link                            # developers: symlink to this checkout"""),
    "update": ("update installed skills from this checkout (backup first); third-party tools are opt-in", """\
examples:
  python3 agent-skills.py status                                    # see what is outdated first
  python3 agent-skills.py update
  python3 agent-skills.py update --with-codegraph                   # also refresh CodeGraph
  python3 agent-skills.py update --force                            # replace hand-edited copies (they are backed up)"""),
    "status": ("show installed vs source, local edits, backups, venv, CodeGraph and ui-ux-pro-max", """\
examples:
  python3 agent-skills.py status
  python3 agent-skills.py status --target claude-project --project ~/work/shop"""),
    "rollback": ("restore the skills from a backup (latest by default)", """\
examples:
  python3 agent-skills.py rollback
  python3 agent-skills.py rollback --backup 20261028T101500123456Z"""),
    "uninstall": ("remove the devskills skills (backed up first); other skills are kept", """\
examples:
  python3 agent-skills.py uninstall --dry-run
  python3 agent-skills.py uninstall --skills verify-ui
  python3 agent-skills.py uninstall --remove-venv                   # also delete ~/.devskills/venv"""),
    "guard": ("remove legacy devskills approval hooks and blanket ask rules (never installs them)", """\
examples:
  python3 agent-skills.py guard --dry-run                           # show the settings.json change
  python3 agent-skills.py guard --remove                            # clean ~/.claude/settings.json
  python3 agent-skills.py guard                                     # same cleanup; never enables a hook
  python3 agent-skills.py guard --target claude-project --local     # clean this project's local settings"""),
    "rules": ("add, refresh or remove the always-loaded devskills rule in a project's CLAUDE.md and/or AGENTS.md", """\
examples:
  python3 agent-skills.py rules --project ~/work/shop               # CLAUDE.md (Claude Code) and AGENTS.md (Codex, others)
  python3 agent-skills.py rules --project ~/work/shop --file agents # AGENTS.md only
  python3 agent-skills.py rules --project ~/work/shop --file claude # CLAUDE.md only
  python3 agent-skills.py rules --project ~/work/shop --remove      # take the rule out again"""),
    "sync": ("developers: copy tools/ds_shim.py into every skill's scripts/ds.py", """\
example:
  python3 agent-skills.py sync"""),
}
TARGET_HELP = ("where to install: claude-user = ~/.claude/skills (default), claude-project = <project>/.claude/skills, "
               "agents = ~/.agents/skills, codex = ~/.codex/skills")


def build_parser() -> argparse.ArgumentParser:
    """CLI definition; every command shares the target options."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="commands:\n" + "\n".join(f"  {name:10} {summary}" for name, (summary, _) in COMMAND_HELP.items())
        + "\n  help       help [command]: this overview or one command's options and examples"
        + "\n\nfirst time: python3 agent-skills.py install --dry-run, then install; afterwards status → update."
        + "\nguide: INSTALL.md")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, (summary, examples) in COMMAND_HELP.items():
        sub = commands.add_parser(name, help=summary, description=summary, epilog=examples,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
        sub.add_argument("--target", default="claude-user", choices=["claude-user", "claude-project", "agents", "codex"],
                         help=TARGET_HELP)
        sub.add_argument("--project", help="project root for --target claude-project (default: current directory)")
        sub.add_argument("--target-dir", help="install into this skills directory instead of a named target")
        sub.add_argument("--render-paths", action="store_true", help="with --target-dir: replace ${CLAUDE_SKILL_DIR} with real paths")
        sub.add_argument("--skills", help="comma-separated subset of skills (default: all 20)")
        sub.add_argument("--dry-run", action="store_true", help="print what would be done; change nothing")
        sub.add_argument("--force", action="store_true", help="replace foreign or locally edited skills (backups are kept)")
        if name == "install":
            sub.add_argument("--link", action="store_true", help="symlink skills to this checkout (development mode)")
        if name in ("install", "update"):
            sub.add_argument("--with-venv", nargs="?", const=str(DEFAULT_VENV), metavar="PATH",
                             help="optional: give the skills their own virtualenv (created only if missing; default ~/.devskills/venv)")
            sub.add_argument("--extras", default=DEFAULT_EXTRAS, help="with --with-venv: ui,imaging,pdf (default); contracts for API-011; or none")
            sub.add_argument("--with-codegraph", action="store_true",
                             help=f"optional: npm install -g {CODEGRAPH_PACKAGE}@latest (call graph for inspect; never runs codegraph init)")
            sub.add_argument("--with-ui-ux-pro-max", action="store_true",
                             help="opt in to installing the UI reference from npm; requires --ui-ux-version")
            sub.add_argument("--ui-ux-version", help="exact reviewed UI CLI release X.Y.Z; never resolves latest")
            sub.add_argument("--with-skill-gate", action="store_true",
                             help="accepted for old scripts: the skill gate is installed by default")
            sub.add_argument("--without-ui-ux-pro-max", action="store_true", help=f"do not install or refresh {UIUX_SKILL}")
            sub.add_argument("--without-agent-rules", action="store_true",
                             help="do not write the always-loaded devskills rule into CLAUDE.md / AGENTS.md")
            sub.add_argument("--without-skill-gate", action="store_true",
                             help="do not install the skill-gate hooks (Claude Code: force skills to be loaded; Codex: style hint)")
        if name == "uninstall":
            sub.add_argument("--remove-venv", action="store_true", help="also delete the skills' virtualenv")
            sub.add_argument("--venv", default=str(DEFAULT_VENV), help="virtualenv to delete with --remove-venv")
        if name == "rules":
            sub.add_argument("--file", default="both", choices=list(RULES_FILES),
                             help="claude = CLAUDE.md (Claude Code), agents = AGENTS.md (Codex, Copilot, Cursor…), both (default)")
            sub.add_argument("--remove", action="store_true", help="remove the rule instead of writing it")
        if name == "rollback":
            sub.add_argument("--backup", help="backup timestamp to restore (default: latest; `status` lists them)")
        if name == "guard":
            sub.add_argument("--mode", default="standard", choices=["standard", "strict", "ask"],
                             help=argparse.SUPPRESS)  # Accepted for old scripts; cleanup only.
            sub.add_argument("--remove", action="store_true", help="remove legacy hooks/rules (also the default)")
            sub.add_argument("--no-ask-rules", action="store_true", help=argparse.SUPPRESS)
            sub.add_argument("--local", action="store_true", help="claude-project: write .claude/settings.local.json")
            sub.add_argument("--settings", help="explicit settings.json path")
    help_command = commands.add_parser("help", help="show this overview, or one command's options and examples")
    help_command.add_argument("topic", nargs="?", choices=list(COMMAND_HELP), help="command to explain")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; errors the user can fix are printed without a traceback."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        if args.topic:
            parser.parse_args([args.topic, "--help"])
        parser.print_help()
        return 0
    args.link = getattr(args, "link", False)
    args.with_venv = getattr(args, "with_venv", None)
    try:
        if args.command == "install":
            return install_or_update(args, update_only=False)
        if args.command == "update":
            return install_or_update(args, update_only=True)
        return {"status": cmd_status, "rollback": cmd_rollback, "uninstall": cmd_uninstall,
                "guard": cmd_guard, "rules": cmd_rules, "sync": cmd_sync}[args.command](args)
    except InstallError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
