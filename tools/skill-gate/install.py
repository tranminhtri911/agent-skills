#!/usr/bin/env python3
"""Install / remove the skill gate for Claude Code (user scope, idempotent).

Opt in with `python3 agent-skills.py install --with-skill-gate`
(`uninstall` removes it). This script does only the gate:

    python3 tools/skill-gate/install.py            # install or update
    python3 tools/skill-gate/install.py --dry-run  # show what would change
    python3 tools/skill-gate/install.py --uninstall

Does three things, each reversible:
  1. copies skill-gate.py to ~/.claude/hooks/skill-gate.py
  2. merges hooks into ~/.claude/settings.json (existing hooks are kept; a timestamped backup is written)
  3. maintains one marked block in ~/.claude/CLAUDE.md
"""
import argparse
import json
import os
import re
import shlex
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "skill-gate.py"
BEGIN, END = "<!-- skill-gate:begin -->", "<!-- skill-gate:end -->"

BLOCK = f"""{BEGIN}
# Skill gate (enforced by hooks; source: agent-skills/tools/skill-gate)
- Route skills by **what the work touches** (the request, the code it changes, the commands it runs), never by file names alone. Load them with the **Skill tool**, never from memory; once loaded, a skill stays loaded for the rest of the session (subagents load their own).
- Order for development work, combining devskills and superpowers: `dev-orchestrate` (routing) -> the superpowers process skill (`systematic-debugging` for a bug, `brainstorming` for a new feature, `writing-plans` for a multi-step plan, `test-driven-development` while implementing) -> **every** devskills domain skill the work touches -> `verification-before-completion` + `review-code` before handover. Where both cover a step, apply both: superpowers says how to work, devskills says which rules the change must meet.
- Re-check the routing each time the work reaches a new area (data, screen, endpoint, external call, auth, test, command).
- Before the first code edit print one line: `Skills: <names actually loaded>`. When delegating to a subagent, name the skills it must load in its prompt.
- End with `Skills applied` listing ONLY skills actually loaded, each with a rule ID. Never list a skill you did not load.
- Hooks enforce this: code edits and test / database / commit commands are denied until their skills are loaded; finishing a request whose skills were never loaded is blocked once (load them, or say in one line why one does not apply). Disable only for debugging: `SKILL_GATE=off`.
{END}
"""


def hook_entries(hook_path):
    """The hook groups to merge into settings.json; every command carries MARKER so it can be found again."""
    base = "python3 " + shlex.quote(hook_path)

    def cmd(sub, timeout=15):
        return {"type": "command", "command": f"{base} {sub}", "timeout": timeout}

    return {
        "UserPromptSubmit": [{"hooks": [cmd("prompt")]}],
        "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [cmd("gate", 30)]}],
        "SubagentStart": [{"hooks": [cmd("subagent")]}],
        "SessionStart": [{"matcher": "compact", "hooks": [cmd("compact")]}],
        "Stop": [{"hooks": [cmd("stop", 30)]}],
    }


def strip_ours(groups):
    out = []
    for group in groups:
        hooks = [h for h in group.get("hooks", []) if MARKER not in h.get("command", "")]
        if hooks:
            out.append(dict(group, hooks=hooks))
    return out


def merge_settings(data, install, hook_path):
    hooks = data.setdefault("hooks", {})
    for event in list(hooks):
        hooks[event] = strip_ours(hooks[event])
        if not hooks[event]:
            del hooks[event]
    if install:
        for event, groups in hook_entries(hook_path).items():
            hooks.setdefault(event, []).extend(groups)
    if not hooks:
        del data["hooks"]
    return data


def merge_claude_md(text, install):
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S).rstrip("\n")
    if install:
        text += "\n\n" + BLOCK
    return text.rstrip("\n") + "\n"


def write(path, content, dry_run, log):
    if dry_run:
        log(f"  skill gate: would write {path}  (dry run)")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def apply(install=True, dry_run=False, claude_dir=None, log=print):
    """Install (or remove) the skill gate under `claude_dir` (default ~/.claude).

    Raises RuntimeError when settings.json is not valid JSON; nothing is changed in that case.
    Running it again on an installed gate only refreshes the copied hook and rewrites identical content.
    """
    claude_dir = claude_dir or os.path.expanduser("~/.claude")
    hook_dst = os.path.join(claude_dir, "hooks", "skill-gate.py")
    settings_path = os.path.join(claude_dir, "settings.json")
    claude_md = os.path.join(claude_dir, "CLAUDE.md")

    try:
        with open(settings_path, encoding="utf-8") as fh:
            raw = fh.read()
        settings = json.loads(raw)
    except FileNotFoundError:
        raw, settings = "", {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{settings_path} is not valid JSON ({exc}); fix it first, nothing changed") from exc

    # One backup per install: skipped when the gate is already in the file (a re-run would only copy itself).
    if raw and MARKER not in raw and not dry_run:
        backup = f"{settings_path}.skill-gate-backup-{time.strftime('%Y%m%dT%H%M%S')}"
        shutil.copy2(settings_path, backup)
        log(f"  skill gate: backup {backup}")

    if install:
        if dry_run:
            log(f"  skill gate: would copy skill-gate.py -> {hook_dst}  (dry run)")
        else:
            os.makedirs(os.path.dirname(hook_dst), exist_ok=True)
            shutil.copy2(os.path.join(HERE, "skill-gate.py"), hook_dst)
            os.chmod(hook_dst, 0o755)
    elif os.path.exists(hook_dst) and not dry_run:
        os.remove(hook_dst)

    updated = json.dumps(merge_settings(settings, install, hook_dst), indent=2, ensure_ascii=False) + "\n"
    if updated != raw or install:
        write(settings_path, updated, dry_run, log)

    md = open(claude_md, encoding="utf-8").read() if os.path.exists(claude_md) else ""
    new_md = merge_claude_md(md, install)
    if new_md != md:
        write(claude_md, new_md, dry_run, log)

    state = "installed" if install else "removed"
    log(f"  skill gate: {state}{'  (dry run)' if dry_run else ''}")
    if install and not dry_run:
        log("    open /hooks once (or restart Claude Code) so running sessions reload the hooks; "
            "escape hatch: SKILL_GATE=off")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="project root; default is explicitly requested user scope")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        apply(install=not args.uninstall, dry_run=args.dry_run,
              claude_dir=os.path.join(os.path.abspath(args.project), ".claude") if args.project else None)
    except RuntimeError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
