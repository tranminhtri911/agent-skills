"""Installer lifecycle (install/status/update/rollback/uninstall/guard) and skill package validity."""

import json
import os
import subprocess
import sys
import unittest

import devskills
from devskills.skillcheck import FrontmatterError, parse_frontmatter, validate_skill
from tests._support import REPO_ROOT, make_temp_dir, run_cli, write

INSTALLER = REPO_ROOT / "agent-skills.py"
SKILL_NAMES = sorted(path.parent.name for path in (REPO_ROOT / "skills").glob("*/SKILL.md"))


class SkillPackageTest(unittest.TestCase):
    def test_all_skills_validate(self):
        completed = run_cli("validate-skills", str(REPO_ROOT / "skills"))
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(len(SKILL_NAMES), 19)

    def test_shims_match_the_canonical_copy(self):
        canonical = (REPO_ROOT / "tools" / "ds_shim.py").read_bytes()
        for name in SKILL_NAMES:
            self.assertEqual((REPO_ROOT / "skills" / name / "scripts" / "ds.py").read_bytes(), canonical,
                             f"{name}: run `python3 agent-skills.py sync`")

    def test_shim_runs_from_the_source_tree(self):
        shim = REPO_ROOT / "skills" / "dev-orchestrate" / "scripts" / "ds.py"
        completed = subprocess.run([sys.executable, str(shim), "--version"], capture_output=True, text=True, check=False)
        self.assertEqual(completed.stdout.strip(), f"devskills {devskills.__version__}", completed.stderr)

    def test_frontmatter_parser(self):
        fields, body, _ = parse_frontmatter('---\nname: x\ndescription: "Use when: quoted"\nmetadata:\n  version: "1"\n---\nBody\n')
        self.assertEqual(fields, {"name": "x", "description": "Use when: quoted", "metadata": {"version": "1"}})
        self.assertEqual(body, "Body\n")
        folded, _, _ = parse_frontmatter("---\nname: x\ndescription: >\n  Use when a\n  b\n---\n")
        self.assertEqual(folded["description"], "Use when a b")
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nname: x\ndescription: Use when: unquoted colon\n---\n")

    def test_validator_reports_problems(self):
        root = make_temp_dir(self)
        write(root, "Bad_Skill/SKILL.md", "---\nname: Bad_Skill\ndescription: Does things\nhooks: x\n---\n"
                                         "Run `ds.py no-such-command` and read [ref](references/missing.md).\n")
        rules = {finding.rule_id for finding in validate_skill(root / "Bad_Skill", {"inspect"})}
        self.assertTrue({"SKILL-NAME", "SKILL-DESCRIPTION-TRIGGER", "SKILL-NONPORTABLE-KEY", "SKILL-UNKNOWN-COMMAND",
                         "SKILL-BROKEN-LINK", "SKILL-SCRIPT-MISSING"} <= rules, rules)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.target = make_temp_dir(self) / "skills"
        self.backups = make_temp_dir(self)

    def installer(self, *args):
        env = dict(os.environ, DEVSKILLS_BACKUP_DIR=str(self.backups), DEVSKILLS_VENV=str(self.backups / "no-venv-here"))
        return subprocess.run([sys.executable, str(INSTALLER), *args, "--target-dir", str(self.target)],
                              capture_output=True, text=True, env=env, check=False, timeout=300)

    def test_default_install_creates_no_venv(self):
        completed = self.installer("install", "--skills", "test-safely")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("venv:", completed.stdout)
        recorded = (self.target / "test-safely" / "scripts" / "_runtime" / "PYTHON").read_text().strip()
        self.assertEqual(recorded, sys.executable, "without --with-venv the installing interpreter is used")
        self.assertFalse((self.backups / "no-venv-here").exists())

    def test_optional_venv_is_created_once_and_used_by_the_shim(self):
        venv = make_temp_dir(self) / "skills-venv"
        first = self.installer("install", "--skills", "dev-orchestrate", "--with-venv", str(venv), "--extras", "none")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("venv: creating", first.stdout)
        venv_python = venv / "bin" / "python"
        recorded = (self.target / "dev-orchestrate" / "scripts" / "_runtime" / "PYTHON").read_text().strip()
        self.assertEqual(recorded, str(venv_python))
        doctor = subprocess.run([sys.executable, str(self.target / "dev-orchestrate" / "scripts" / "ds.py"), "doctor", "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(doctor.stdout)["python"]["executable"], str(venv_python),
                         "ds.py relaunches itself with the skills' venv whatever interpreter started it")
        again = self.installer("update", "--skills", "dev-orchestrate", "--with-venv", str(venv), "--extras", "none")
        self.assertIn("venv: using existing", again.stdout)
        self.assertIn("up to date", again.stdout)
        plain_update = self.installer("update", "--skills", "dev-orchestrate")
        self.assertIn("up to date", plain_update.stdout, "an update without --with-venv keeps the recorded venv")
        self.assertEqual(self.installer("status", "--skills", "dev-orchestrate").returncode, 0, "status reuses the recorded venv")
        removed = self.installer("uninstall", "--remove-venv", "--venv", str(venv))
        self.assertEqual(removed.returncode, 0, removed.stdout)
        self.assertFalse(venv.exists())
        self.assertEqual(self.installer("install", "--with-venv", str(venv), "--extras", "nonsense").returncode, 2)

    def test_help_lists_every_command_with_examples(self):
        overview = subprocess.run([sys.executable, str(INSTALLER), "help"], capture_output=True, text=True, check=False)
        self.assertEqual(overview.returncode, 0, overview.stderr)
        for command in ("install", "update", "status", "rollback", "uninstall", "guard", "sync"):
            self.assertIn(f"  {command}", overview.stdout)
        install_help = subprocess.run([sys.executable, str(INSTALLER), "help", "install"], capture_output=True, text=True, check=False)
        self.assertEqual(install_help.returncode, 0)
        self.assertIn("--with-ui-ux-pro-max", install_help.stdout)
        self.assertIn("examples:", install_help.stdout)
        self.assertNotIn("\n  --dry-run\n", install_help.stdout, "every option has a description")

    def test_optional_tools_install_latest_without_sudo(self):
        project = make_temp_dir(self)
        fake_bin = make_temp_dir(self)
        log = fake_bin / "calls.log"
        # Fake npm/npx/codegraph record their argv; npx "installs" the skill into the project like uipro does.
        for name, body in {
            "npm": 'echo "npm $*" >> "$LOG"',
            "npx": 'echo "npx $* (cwd $PWD)" >> "$LOG"; mkdir -p .claude/skills/ui-ux-pro-max; echo "# ui" > .claude/skills/ui-ux-pro-max/SKILL.md',
            "codegraph": 'echo "codegraph 9.9.9"',
        }.items():
            script = fake_bin / name
            script.write_text(f"#!/bin/sh\n{body}\n")
            script.chmod(0o755)
        env = dict(os.environ, DEVSKILLS_BACKUP_DIR=str(self.backups), LOG=str(log), PATH=f"{fake_bin}:{os.environ['PATH']}")

        def run(*args):
            return subprocess.run([sys.executable, str(INSTALLER), *args, "--target", "claude-project", "--project", str(project)],
                                  capture_output=True, text=True, env=env, check=False, timeout=300)

        dry = run("install", "--skills", "verify-ui", "--dry-run", "--with-codegraph", "--with-ui-ux-pro-max", "--ui-ux-version", "1.2.3")
        self.assertIn("--registry=https://registry.npmjs.org ui-ux-pro-max-cli@1.2.3 init --ai claude", dry.stdout)
        self.assertFalse(log.exists(), "a dry run calls nothing")
        first = run("install", "--skills", "verify-ui", "--with-codegraph", "--with-ui-ux-pro-max", "--ui-ux-version", "1.2.3")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        calls = log.read_text()
        self.assertIn("npm install -g @colbymchenry/codegraph@latest", calls)
        self.assertIn(f"npx -y --registry=https://registry.npmjs.org ui-ux-pro-max-cli@1.2.3 init --ai claude (cwd {project.resolve()})", calls)
        self.assertNotIn("sudo", calls + first.stdout)
        self.assertNotIn("--global", calls, "a project target installs into the project")
        skill = project / ".claude" / "skills" / "ui-ux-pro-max" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertIn("codegraph 9.9.9", first.stdout)
        skill.write_text("# edited by hand\n")
        run("update", "--skills", "verify-ui", "--force", "--with-ui-ux-pro-max", "--ui-ux-version", "1.2.3")
        backups = list(self.backups.rglob("ui-ux-pro-max/SKILL.md"))
        self.assertEqual([path.read_text() for path in backups], ["# edited by hand\n"], "the previous copy is backed up first")
        status = run("status", "--skills", "verify-ui")
        self.assertIn("ui-ux-pro-max (UI design reference, opt-in): installed", status.stdout)
        unsupported = self.installer("install", "--skills", "verify-ui", "--with-ui-ux-pro-max", "--ui-ux-version", "1.2.3")
        self.assertEqual(unsupported.returncode, 1)
        self.assertIn("no uipro mapping for --target-dir", unsupported.stdout)

        # Optional tools never run during default installation/update.
        log.unlink()
        default = run("update", "--skills", "verify-ui")
        self.assertEqual(default.returncode, 0, default.stdout + default.stderr)
        self.assertFalse(log.exists())
        self.assertEqual(run("update", "--skills", "verify-ui", "--without-ui-ux-pro-max").returncode, 0)
        self.assertFalse(log.exists(), "--without-ui-ux-pro-max calls nothing")
        skipped = self.installer("install", "--skills", "verify-ui")
        self.assertEqual(skipped.returncode, 0, skipped.stdout + skipped.stderr)
        self.assertNotIn("npx -y", skipped.stdout)

    def test_agent_rules_are_written_updated_and_removed(self):
        project = make_temp_dir(self)
        claude_md = project / "CLAUDE.md"
        hand_copy = "# Development skills (devskills)\nold hand-pasted wording\n"
        claude_md.write_text("# Team rules\nKeep PRs small.\n\n" + hand_copy + "\n# Other\nMore rules.\n")
        env = dict(os.environ, DEVSKILLS_BACKUP_DIR=str(self.backups))

        def run(*args):
            extra = ["--without-ui-ux-pro-max"] if args[0] in ("install", "update") else []
            return subprocess.run([sys.executable, str(INSTALLER), *args, "--target", "claude-project",
                                   "--project", str(project), *extra],
                                  capture_output=True, text=True, env=env, check=False, timeout=300)

        rules = (REPO_ROOT / "tools" / "agent-rules.md").read_text().strip()
        dry = run("install", "--skills", "dev-orchestrate", "--with-skill-gate", "--dry-run")
        self.assertIn("agent rules: update in", dry.stdout)
        self.assertIn("old hand-pasted wording", claude_md.read_text(), "a dry run writes nothing")

        first = run("install", "--skills", "dev-orchestrate", "--with-skill-gate")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        text = claude_md.read_text()
        self.assertEqual(text.count("devskills:agent-rules begin"), 1)
        self.assertIn(rules, text)
        self.assertNotIn("old hand-pasted wording", text, "the hand copy is replaced, not duplicated")
        self.assertIn("# Team rules\nKeep PRs small.", text)
        self.assertIn("# Other\nMore rules.", text, "sections after the rule are kept")
        self.assertTrue(list((self.backups / "agent-rules").glob("*CLAUDE_md")), "the previous file is backed up")

        again = run("update", "--skills", "dev-orchestrate", "--with-skill-gate")
        self.assertIn("agent rules: up to date", again.stdout)
        self.assertEqual(claude_md.read_text(), text, "a second run changes nothing")
        self.assertIn("agent rules (always-loaded, makes agents use dev-orchestrate): up-to-date",
                      run("status", "--skills", "dev-orchestrate").stdout)

        removed = run("uninstall", "--skills", "dev-orchestrate")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        text = claude_md.read_text()
        self.assertNotIn("devskills", text)
        self.assertEqual(text, "# Team rules\nKeep PRs small.\n\n# Other\nMore rules.\n")

        other = make_temp_dir(self)
        for args in (("install", "--skills", "verify-ui"), ("install", "--skills", "dev-orchestrate", "--without-agent-rules")):
            completed = subprocess.run([sys.executable, str(INSTALLER), *args, "--target", "claude-project",
                                        "--project", str(other), "--without-ui-ux-pro-max"],
                                       capture_output=True, text=True, env=env, check=False, timeout=300)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertFalse((other / "CLAUDE.md").exists(), f"{args}: no rule without dev-orchestrate or when opted out")

    def test_skill_gate_is_installed_with_the_skills_and_removed_by_uninstall(self):
        home = make_temp_dir(self)
        claude_dir = home / ".claude"
        other_hook = {"type": "command", "command": "graphify hook-guard search", "timeout": 5}
        write(home, ".claude/settings.json", json.dumps({
            "model": "sonnet", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [other_hook]}]}}))
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(self.backups))

        def run(*args, target="claude-user"):
            extra = ["--without-ui-ux-pro-max"] if args[0] in ("install", "update") else []
            return subprocess.run([sys.executable, str(INSTALLER), *args, "--target", target, *extra],
                                  capture_output=True, text=True, env=env, check=False, timeout=300)

        def gate_commands(data):
            return [hook["command"] for groups in data.get("hooks", {}).values() for group in groups
                    for hook in group["hooks"] if "skill-gate.py" in hook["command"]]

        settings_path = claude_dir / "settings.json"
        before = settings_path.read_text()
        dry = run("install", "--skills", "dev-orchestrate", "--with-skill-gate", "--dry-run")
        self.assertIn("skill gate:", dry.stdout)
        self.assertEqual(settings_path.read_text(), before, "a dry run writes nothing")
        self.assertFalse((claude_dir / "hooks").exists())

        first = run("install", "--skills", "dev-orchestrate", "--with-skill-gate")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        data = json.loads(settings_path.read_text())
        self.assertEqual(len(gate_commands(data)), 5, "prompt, gate, subagent, compact and stop hooks")
        self.assertIn(other_hook, data["hooks"]["PreToolUse"][0]["hooks"], "existing hooks are kept")
        self.assertEqual(data["model"], "sonnet")
        self.assertTrue((claude_dir / "hooks" / "skill-gate.py").is_file())
        self.assertEqual((claude_dir / "CLAUDE.md").read_text().count("skill-gate:begin"), 1)
        self.assertEqual(len(list(claude_dir.glob("settings.json.skill-gate-backup-*"))), 1)

        installed = settings_path.read_text()
        again = run("update", "--skills", "dev-orchestrate", "--with-skill-gate")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(settings_path.read_text(), installed, "a second run adds no duplicate hooks")
        self.assertEqual((claude_dir / "CLAUDE.md").read_text().count("skill-gate:begin"), 1)
        self.assertEqual(len(list(claude_dir.glob("settings.json.skill-gate-backup-*"))), 1,
                         "a re-run does not overwrite the original backup")

        removed = run("uninstall", "--skills", "dev-orchestrate")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        data = json.loads(settings_path.read_text())
        self.assertEqual(gate_commands(data), [])
        self.assertEqual(data["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": [other_hook]}])
        self.assertFalse((claude_dir / "hooks" / "skill-gate.py").exists())
        self.assertNotIn("skill-gate", (claude_dir / "CLAUDE.md").read_text())

        for args, target in ((("install", "--skills", "dev-orchestrate", "--without-skill-gate"), "claude-user"),
                             (("install", "--skills", "verify-ui"), "claude-user")):
            completed = run(*args, target=target)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(gate_commands(json.loads(settings_path.read_text())), [],
                             f"{args}: no gate when opted out or without dev-orchestrate")

        project = make_temp_dir(self)
        completed = subprocess.run([sys.executable, str(INSTALLER), "install", "--skills", "dev-orchestrate",
                                    "--target", "claude-project", "--project", str(project), "--without-ui-ux-pro-max"],
                                   capture_output=True, text=True, env=env, check=False, timeout=300)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(gate_commands(json.loads(settings_path.read_text())), [], "project installs never touch user hooks")

    def test_codex_gets_the_style_hook_by_default_next_to_its_existing_hooks(self):
        home = make_temp_dir(self)
        other_hook = {"type": "command", "command": "graphify hook-check"}
        hooks_path = write(home, ".codex/hooks.json", json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [other_hook]}]}}))
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(self.backups))

        def run(*args):
            extra = ["--without-ui-ux-pro-max"] if args[0] in ("install", "update") else []
            return subprocess.run([sys.executable, str(INSTALLER), *args, "--target", "codex", *extra],
                                  capture_output=True, text=True, env=env, check=False, timeout=300)

        def gate_groups():
            data = json.loads(hooks_path.read_text())
            return [(group.get("matcher"), hook["command"]) for groups in data["hooks"].values() for group in groups
                    for hook in group["hooks"] if "skill-gate.py" in hook["command"]]

        before = hooks_path.read_text()
        dry = run("install", "--skills", "dev-orchestrate", "--dry-run")
        self.assertIn("skill gate:", dry.stdout)
        self.assertEqual(hooks_path.read_text(), before, "a dry run writes nothing")

        first = run("install", "--skills", "dev-orchestrate")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        groups = gate_groups()
        self.assertEqual(len(groups), 1, "one hook: the style hint on apply_patch")
        self.assertEqual(groups[0][0], "^apply_patch$")
        self.assertTrue(groups[0][1].endswith(" codex-style"), groups[0][1])
        self.assertIn(other_hook, json.loads(hooks_path.read_text())["hooks"]["PreToolUse"][0]["hooks"])
        self.assertTrue((home / ".codex" / "hooks" / "skill-gate.py").is_file())
        self.assertFalse((home / ".claude").exists(), "Codex installs never touch Claude settings")
        self.assertIn("/hooks", first.stdout, "Codex asks the user to trust a new hook")

        run("update", "--skills", "dev-orchestrate")
        self.assertEqual(len(gate_groups()), 1, "installing or updating again does not duplicate the hook")

        removed = run("uninstall", "--skills", "dev-orchestrate")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertEqual(gate_groups(), [])
        self.assertIn(other_hook, json.loads(hooks_path.read_text())["hooks"]["PreToolUse"][0]["hooks"])

        opted_out = run("install", "--skills", "dev-orchestrate", "--without-skill-gate")
        self.assertEqual(opted_out.returncode, 0, opted_out.stdout + opted_out.stderr)
        self.assertEqual(gate_groups(), [], "--without-skill-gate leaves the hooks alone")

    def test_claude_gets_the_gate_by_default_and_can_opt_out(self):
        home = make_temp_dir(self)
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(self.backups))

        def run(*extra):
            return subprocess.run([sys.executable, str(INSTALLER), "install", "--skills", "dev-orchestrate",
                                   "--target", "claude-user", "--without-ui-ux-pro-max", *extra],
                                  capture_output=True, text=True, env=env, check=False, timeout=300)

        opted_out = run("--without-skill-gate")
        self.assertEqual(opted_out.returncode, 0, opted_out.stdout + opted_out.stderr)
        self.assertFalse((home / ".claude" / "hooks").exists())
        plain = run()
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertTrue((home / ".claude" / "hooks" / "skill-gate.py").is_file(), "no flag needed any more")
        self.assertIn("skill-gate.py", (home / ".claude" / "settings.json").read_text())

    def test_skill_gate_refuses_invalid_settings_without_changing_anything(self):
        home = make_temp_dir(self)
        broken = write(home, ".claude/settings.json", "{not json")
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(self.backups))
        completed = subprocess.run([sys.executable, str(INSTALLER), "install", "--skills", "dev-orchestrate",
                                    "--target", "claude-user", "--with-skill-gate", "--without-ui-ux-pro-max"],
                                   capture_output=True, text=True, env=env, check=False, timeout=300)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not valid JSON", completed.stdout)
        self.assertEqual(broken.read_text(), "{not json")
        self.assertFalse((home / ".claude" / "hooks").exists())

    def test_rules_command_targets_a_chosen_project(self):
        project = make_temp_dir(self)
        (project / "AGENTS.md").write_text("# Repo guide\nUse pnpm.\n")
        env = dict(os.environ, DEVSKILLS_BACKUP_DIR=str(self.backups))

        def rules(*args):
            return subprocess.run([sys.executable, str(INSTALLER), "rules", "--project", str(project), *args],
                                  capture_output=True, text=True, env=env, check=False, timeout=60)

        self.assertEqual(rules("--file", "agents").returncode, 0)
        self.assertFalse((project / "CLAUDE.md").exists(), "--file agents writes AGENTS.md only")
        agents = (project / "AGENTS.md").read_text()
        self.assertTrue(agents.startswith("# Repo guide\nUse pnpm.\n\n<!-- devskills:agent-rules begin"))
        both = rules()
        self.assertIn("agent rules: up to date", both.stdout)
        self.assertIn("agent rules: add to", both.stdout)
        self.assertIn("devskills:agent-rules begin", (project / "CLAUDE.md").read_text())
        self.assertEqual(rules("--remove").returncode, 0)
        self.assertEqual((project / "AGENTS.md").read_text(), "# Repo guide\nUse pnpm.\n")
        self.assertNotIn("devskills", (project / "CLAUDE.md").read_text())
        missing = subprocess.run([sys.executable, str(INSTALLER), "rules", "--project", str(project / "nope")],
                                 capture_output=True, text=True, env=env, check=False, timeout=60)
        self.assertNotEqual(missing.returncode, 0)

    def test_install_status_update_rollback_uninstall(self):
        installed = self.installer("install")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertIn("19 skill(s) valid", installed.stdout)
        skill = self.target / "dev-orchestrate"
        self.assertTrue((skill / "scripts" / "_runtime" / "devskills" / "cli.py").is_file())
        manifest = json.loads((skill / "scripts" / "_runtime" / "MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], devskills.__version__)
        self.assertIn("${CLAUDE_SKILL_DIR}", (skill / "SKILL.md").read_text(), "Claude-style install keeps placeholders")
        version = subprocess.run([sys.executable, "-I", str(skill / "scripts" / "ds.py"), "--version"], capture_output=True, text=True, check=False)
        self.assertEqual(version.stdout.strip(), f"devskills {devskills.__version__}", "the vendored runtime works in isolated mode")
        doctor = subprocess.run([sys.executable, str(skill / "scripts" / "ds.py"), "doctor", "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(doctor.stdout)["runtime"]["integrity"], "ok")

        self.assertEqual(self.installer("status").returncode, 0)
        edited = skill / "SKILL.md"
        edited.write_text(edited.read_text() + "\nlocal note\n")
        status = self.installer("status")
        self.assertIn("local edit", status.stdout)
        refused = self.installer("update", "--skills", "dev-orchestrate")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("edited by hand", refused.stdout)
        self.assertIn("local note", edited.read_text(), "manual edits are never overwritten without --force")

        forced = self.installer("update", "--skills", "dev-orchestrate", "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertNotIn("local note", edited.read_text())
        rollback = self.installer("rollback")
        self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
        self.assertIn("local note", edited.read_text(), "rollback restores the backed-up version")

        removed = self.installer("uninstall", "--skills", "verify-ui")
        self.assertEqual(removed.returncode, 0)
        self.assertFalse((self.target / "verify-ui").exists())
        self.assertIn("missing    verify-ui", self.installer("status").stdout)

    def test_foreign_skill_is_protected(self):
        write(self.target, "verify-ui/SKILL.md", "---\nname: verify-ui\ndescription: Use when mine\n---\nmine\n")
        completed = self.installer("install", "--skills", "verify-ui")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("not installed by devskills", completed.stdout)
        self.assertIn("mine", (self.target / "verify-ui" / "SKILL.md").read_text())
        forced = self.installer("install", "--skills", "verify-ui", "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout)
        backups = list(self.backups.rglob("verify-ui/SKILL.md"))
        self.assertTrue(backups and "mine" in backups[0].read_text())

    def test_rendered_paths_for_other_hosts(self):
        completed = self.installer("install", "--skills", "test-safely", "--render-paths")
        self.assertEqual(completed.returncode, 0, completed.stdout)
        text = (self.target / "test-safely" / "SKILL.md").read_text()
        self.assertNotIn("${CLAUDE_SKILL_DIR}", text)
        self.assertIn(str(self.target / "test-safely"), text)

    def test_guard_removes_legacy_settings_and_preserves_other_hooks(self):
        settings = make_temp_dir(self) / "settings.json"
        other_hook = {"type": "command", "command": "check-project-policy", "timeout": 5}
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": 'python3 "/skills/ds.py" guard --mode strict'}, other_hook]},
                {"matcher": "Read", "hooks": [other_hook]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 ds.py guard"}]},
            ], "PostToolUse": [{"matcher": "Write", "hooks": [other_hook]}]},
            "permissions": {"allow": ["Bash(npm test)"],
                            "ask": ["Bash(make deploy)", "Bash(rm -rf *)", "Bash(* migrate:fresh*)", "Bash(git clean *)"]},
            "model": "x",
        }))
        removed = self.installer("guard", "--settings", str(settings), "--remove")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        data = json.loads(settings.read_text())
        self.assertEqual(data["hooks"]["PreToolUse"], [
            {"matcher": "Bash", "hooks": [other_hook]}, {"matcher": "Read", "hooks": [other_hook]},
        ])
        self.assertEqual(data["hooks"]["PostToolUse"], [{"matcher": "Write", "hooks": [other_hook]}])
        self.assertEqual(data["permissions"]["allow"], ["Bash(npm test)"])
        self.assertEqual(data["permissions"]["ask"], ["Bash(make deploy)"])
        self.assertEqual(data["model"], "x")
        self.assertEqual(len(list(settings.parent.glob("settings.json.devskills-backup-*"))), 1)
        original = settings.read_bytes()
        for arguments in [[], ["--remove"], ["--mode", "strict"], ["--mode", "ask", "--no-ask-rules"]]:
            completed = self.installer("guard", "--settings", str(settings), *arguments)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(settings.read_bytes(), original)
        self.assertEqual(len(list(settings.parent.glob("settings.json.devskills-backup-*"))), 1)

    def test_guard_does_not_create_missing_settings(self):
        settings = make_temp_dir(self) / "missing" / "settings.json"
        for arguments in [[], ["--remove"], ["--mode", "strict"]]:
            completed = self.installer("guard", "--settings", str(settings), *arguments)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertFalse(settings.parent.exists())

    def test_guard_dry_run_does_not_change_settings(self):
        settings = make_temp_dir(self) / "settings.json"
        settings.write_text(json.dumps({"permissions": {"ask": ["Bash(rm -rf *)"]}}))
        original = settings.read_bytes()
        completed = self.installer("guard", "--settings", str(settings), "--dry-run")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(settings.read_bytes(), original)
        self.assertFalse(list(settings.parent.glob("*.devskills-backup-*")))

    def test_guard_removes_empty_managed_sections(self):
        settings = make_temp_dir(self) / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python3 ds.py guard"}]}]},
            "permissions": {"ask": ["Bash(rm -rf *)"]}, "model": "x",
        }))
        completed = self.installer("guard", "--settings", str(settings))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(settings.read_text()), {"model": "x"})

    def test_guard_refuses_invalid_settings(self):
        settings = make_temp_dir(self) / "settings.json"
        settings.write_text("{ broken")
        completed = self.installer("guard", "--settings", str(settings))
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(settings.read_text(), "{ broken")


class SuiteVersionTest(unittest.TestCase):
    """Every released change bumps one suite version (1.0.0 -> 1.0.1); all copies of it must agree."""

    def test_package_runtime_skills_and_changelog_share_one_version(self):
        version = devskills.__version__
        pyproject = (REPO_ROOT / "pyproject.toml").read_text()
        self.assertIn(f'version = "{version}"', pyproject, "pyproject.toml and src/devskills/__init__.py differ")
        for skill_md in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
            fields, _, _ = parse_frontmatter(skill_md.read_text())
            self.assertEqual(fields["metadata"]["version"], version, f"{skill_md.parent.name}: metadata.version")
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
        self.assertRegex(changelog, rf"(?m)^## {version.replace('.', '[.]')}\b", "CHANGELOG.md needs a section for this version")


if __name__ == "__main__":
    unittest.main()
