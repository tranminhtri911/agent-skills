"""Regressions for installer consent, profile defaults, isolation and release hygiene."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests._support import REPO_ROOT, make_temp_dir, write
from devskills.profile import load_profile
from devskills.runner import execute_check


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChecklistRegressionTest(unittest.TestCase):
    def test_install_without_the_gate_never_calls_third_party_or_writes_hooks(self):
        home = make_temp_dir(self)
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(home / 'backups'))
        # Deliberately invalid JSON: an install that opts out of the gate must not even parse hook settings.
        settings = write(home, '.claude/settings.json', '{keep untouched')
        completed = subprocess.run([sys.executable, str(REPO_ROOT / 'agent-skills.py'), 'install',
                                    '--skills', 'dev-orchestrate', '--without-skill-gate'],
                                   env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn('npx', completed.stdout)
        self.assertFalse((home / '.claude/hooks').exists())
        self.assertEqual(settings.read_text(), '{keep untouched')

    def test_project_gate_does_not_touch_user_hook_settings(self):
        home, project = make_temp_dir(self), make_temp_dir(self)
        user_settings = write(home, '.claude/settings.json', '{do not parse')
        env = dict(os.environ, HOME=str(home), DEVSKILLS_BACKUP_DIR=str(home / 'backups'))
        completed = subprocess.run([sys.executable, str(REPO_ROOT / 'agent-skills.py'), 'install',
                                    '--skills', 'dev-orchestrate', '--target', 'claude-project',
                                    '--project', str(project), '--with-skill-gate'],
                                   env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        settings = json.loads((project / '.claude/settings.json').read_text())
        commands = [hook['command'] for group in settings['hooks']['PreToolUse'] for hook in group['hooks']]
        self.assertTrue(any('skill-gate.py' in command for command in commands))
        self.assertTrue((project / '.claude/hooks/skill-gate.py').exists())
        self.assertEqual(user_settings.read_text(), '{do not parse')

    def test_ui_install_rejects_unpinned_version_before_writing(self):
        root = make_temp_dir(self)
        for version in ([], ['--ui-ux-version', 'latest'], ['--ui-ux-version', '1.2.3;echo BAD']):
            target = root / 'skills'
            completed = subprocess.run([sys.executable, str(REPO_ROOT / 'agent-skills.py'), 'install',
                                        '--target-dir', str(target), '--with-ui-ux-pro-max', *version],
                                       text=True, capture_output=True)
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertFalse(target.exists())

    def test_modes_preserve_strict_for_high_risk(self):
        from devskills.risk import execution_mode
        self.assertEqual([execution_mode(risk) for risk in ('R0', 'R1', 'R2', 'R3')],
                         ['lightweight', 'standard', 'strict', 'strict'])

    def test_profile_preserves_project_choice(self):
        root = make_temp_dir(self)
        profile, _ = load_profile(root)
        self.assertEqual(profile['database']['foreign_key_policy'], 'allowed')
        self.assertEqual(profile['code']['multiline_comment_style'], 'off')
        write(root, '.devskills.toml', '[database]\nforeign_key_policy = "forbidden"\n[code]\nmultiline_comment_style = "line"\n')
        profile, _ = load_profile(root)
        self.assertEqual(profile['database']['foreign_key_policy'], 'forbidden')
        self.assertEqual(profile['code']['multiline_comment_style'], 'line')

    def test_skill_documents_do_not_mandate_house_defaults_over_project_conventions(self):
        # P0-04 / P2-02: references must not reinstate the old blanket comment-style or no-FK rules.
        mandates = ('Multi-line comments use `/* … */`', 'no new DB foreign keys', 'new FKs discouraged')
        for path in sorted((REPO_ROOT / 'skills').rglob('*.md')):
            text = path.read_text(encoding='utf-8')
            for mandate in mandates:
                self.assertNotIn(mandate, text, f'{path.relative_to(REPO_ROOT)} still mandates: {mandate}')

    def test_target_classification_rule_is_documented_and_evaluated(self):
        # OPS-014: only proven-local targets proceed; tunnels, network mounts and indirect commands are not proof.
        reference = (REPO_ROOT / 'skills/dev-orchestrate/references/dangerous-operations.md').read_text(encoding='utf-8')
        for phrase in ('OPS-014', 'Proven local', 'Unknown', 'tunnel', 'network mount', 'npm run',
                       'countdown'):
            self.assertIn(phrase, reference)
        self.assertIn('OPS-014', (REPO_ROOT / 'skills/dev-orchestrate/SKILL.md').read_text(encoding='utf-8'))
        scenarios = json.loads((REPO_ROOT / 'evals/scenarios.json').read_text(encoding='utf-8'))['scenarios']
        self.assertTrue(any('OPS-014' in scenario['expect'] for scenario in scenarios))

    def test_risky_profiles_do_not_start_process_without_os_isolation(self):
        root = make_temp_dir(self)
        for profile in ('integration_isolated', 'performance_isolated', 'provider_sandbox'):
            with self.subTest(profile=profile), patch('devskills.runner.plan_network_enforcement',
                    return_value=([], 'python_socket_guard_only(partial)')), patch('devskills.runner.execute_once') as spawn:
                result, _ = execute_check(root, [sys.executable, '-c', 'raise RuntimeError("must not run")'],
                                          check_id="tests.isolation", profile_name=profile, allowed_hosts={'sandbox.example.invalid'}
                                          if profile == 'provider_sandbox' else set())
                self.assertEqual(result.domain_result, 'network_isolation_unavailable')
                spawn.assert_not_called()

    def test_scenario_ids_and_validator_detect_duplicates(self):
        validator = load_tool('validate-evals')
        self.assertEqual(validator.validate(REPO_ROOT / 'evals/scenarios.json'), [])
        root = make_temp_dir(self)
        case = {'id': 'EV1', 'skill': 'test-safely', 'task': 'test', 'expect': 'blocked'}
        file = write(root, 'cases.json', json.dumps({'scenarios': [case, case]}))
        self.assertIn('duplicate', validator.validate(file)[0])

    def test_release_excludes_state_secrets_and_symlinks(self):
        root = make_temp_dir(self)
        write(root, 'README.md', 'guide')
        write(root, 'src/devskills/a.py', '# code')
        for path in ('.git/config', '.devskills/log.txt', 'src/__pycache__/a.py', 'src/.env', 'src/a.log',
                     'src/devskills.egg-info/SOURCES.txt', 'build/lib/devskills/a.py', 'tests/x/__MACOSX/a.py'):
            write(root, path, 'must not ship')
        try:
            (root / 'src/link.py').symlink_to(root / 'README.md')
        except OSError:
            pass  # Windows can lack symlink privileges; other exclusion assertions still run.
        files = {name for _, name in load_tool('package-release').release_files(root)}
        self.assertEqual(files, {'README.md', 'src/devskills/a.py'})
