"""Automatic style routing: languages, frameworks and style tools detected from the source, per project root."""

import json
import os
import subprocess
import sys
import unittest

# tests._support puts src/ on sys.path, so it must be imported before devskills.
from tests._support import REPO_ROOT, make_temp_dir, write  # noqa: I001
from devskills.style_routing import detect_style, style_for_file

CODE_STYLE_DS = REPO_ROOT / "skills" / "code-style" / "scripts" / "ds.py"
GATE = REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py"


def make_monorepo(test_case):
    root = make_temp_dir(test_case)
    write(root, ".editorconfig", "root = true\n")
    write(root, "api/pyproject.toml", '[project]\nname = "api"\ndependencies = ["django>=5"]\n[tool.ruff]\nline-length = 100\n')
    write(root, "api/billing/views.py", "def list_invoices(request):\n    return None\n")
    write(root, "api/billing/models.py", "class Invoice:\n    pass\n")
    write(root, "web/package.json", json.dumps({"dependencies": {"next": "15.0.0", "react": "19.0.0"}}))
    write(root, "web/.prettierrc", "{}\n")
    write(root, "web/app/page.tsx", "export default function Page() {\n  return null;\n}\n")
    write(root, "mobile/pubspec.yaml", "name: mobile\ndependencies:\n  flutter:\n    sdk: flutter\n")
    write(root, "mobile/analysis_options.yaml", "include: package:flutter_lints/flutter.yaml\n")
    write(root, "mobile/lib/main.dart", "void main() {}\n")
    write(root, "android/app/build.gradle.kts", 'plugins { id("com.android.application") }\nandroid { buildFeatures { compose = true } }\n')
    write(root, "android/app/src/main/kotlin/InvoiceList.kt", "fun invoiceList() = Unit\n")
    write(root, "ios/Package.swift", "// swift-tools-version:5.9\n")
    write(root, "ios/Sources/InvoiceView.swift", "import SwiftUI\nstruct InvoiceView: View { var body: some View { Text(\"\") } }\n")
    write(root, "admin/Admin.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>\n')
    write(root, "admin/Program.cs", "var builder = WebApplication.CreateBuilder(args);\n")
    write(root, "tools/report.go", "package tools\n")
    return root


def roots_by_path(detection):
    return {item["root"]: item for item in detection["roots"]}


class DetectStyleTest(unittest.TestCase):
    def test_each_project_root_gets_its_language_and_framework_references(self):
        roots = roots_by_path(detect_style(make_monorepo(self)))
        expected = {
            "api": ["language-python.md", "framework-django.md"],
            "web": ["language-typescript.md", "framework-react.md"],
            "mobile": ["language-dart.md", "framework-flutter.md"],
            "android/app": ["language-kotlin.md", "framework-android-compose.md"],
            "ios": ["language-swift.md", "framework-swiftui.md"],
            "admin": ["language-csharp.md", "framework-aspnet-core.md"],
        }
        for root, references in expected.items():
            self.assertIn(root, roots, f"{root} not detected as a project root; got {sorted(roots)}")
            for reference in references:
                self.assertIn(reference, roots[root]["references"], f"{root}: {roots[root]}")

    def test_files_outside_any_manifest_belong_to_the_repository_root(self):
        roots = roots_by_path(detect_style(make_monorepo(self)))
        self.assertIn("language-go.md", roots["."]["references"])
        self.assertNotIn("framework-django.md", roots["."]["references"], "frameworks stay with their own root")

    def test_repository_style_tools_are_listed_and_inherited_from_the_top(self):
        roots = roots_by_path(detect_style(make_monorepo(self)))
        self.assertIn("api/pyproject.toml [tool.ruff]", roots["api"]["style_tools"])
        self.assertIn(".editorconfig", roots["api"]["style_tools"], "repository-wide config applies to every root")
        self.assertIn("web/.prettierrc", roots["web"]["style_tools"])
        self.assertIn("mobile/analysis_options.yaml", roots["mobile"]["style_tools"])

    def test_a_single_file_gets_its_own_language_and_its_roots_frameworks(self):
        repo = make_monorepo(self)
        detection = detect_style(repo)
        view = style_for_file(repo, "api/billing/views.py", detection)
        self.assertEqual(view["language"], "python")
        self.assertEqual(view["root"], "api")
        self.assertEqual(view["references"], ["language-python.md", "framework-django.md"])
        page = style_for_file(repo, "web/app/page.tsx", detection)
        self.assertEqual(page["references"], ["language-typescript.md", "framework-react.md"])
        self.assertIsNone(style_for_file(repo, "web/.prettierrc", detection)["language"], "config files are not code")


class InspectStyleSectionTest(unittest.TestCase):
    def test_context_map_lists_style_references(self):
        from devskills.inventory import build_context_map, render_markdown
        context_map = build_context_map(make_monorepo(self), [], 20000)
        self.assertIn("framework-django.md", roots_by_path(context_map["style"])["api"]["references"])
        self.assertIn("framework-flutter.md", render_markdown(context_map))


class StyleCommandTest(unittest.TestCase):
    def run_style(self, repo, *arguments):
        completed = subprocess.run([sys.executable, str(CODE_STYLE_DS), "style", "--repo", str(repo), *arguments],
                                   capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def test_command_prints_references_per_root(self):
        output = self.run_style(make_monorepo(self))
        self.assertIn("api", output)
        self.assertIn("framework-django.md", output)
        self.assertIn("framework-flutter.md", output)

    def test_command_answers_for_one_file_as_json(self):
        repo = make_monorepo(self)
        result = json.loads(self.run_style(repo, "--path", str(repo / "android/app/src/main/kotlin/InvoiceList.kt"), "--json"))
        self.assertEqual(result["language"], "kotlin")
        self.assertEqual(result["references"], ["language-kotlin.md", "framework-android-compose.md"])


class GateStyleHintTest(unittest.TestCase):
    """The skill gate tells Claude which style references apply the first time it edits a language in a root."""

    def setUp(self):
        self.home = make_temp_dir(self)
        self.transcript = write(self.home, "session.jsonl", "")
        self.repo = make_monorepo(self)
        if any(part in str(self.repo).lower() for part in ("/tmp/", "/private/tmp/")):
            self.skipTest("temp dir is on a path the gate skips by design")
        with self.transcript.open("a") as handle:
            for skill in ("dev-orchestrate", "discover-codebase", "write-maintainable-code", "code-style"):
                handle.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]}}) + "\n")

    def edit(self, rel_path):
        env = dict(os.environ, HOME=str(self.home), DEVSKILLS_CODE_STYLE_DS=str(CODE_STYLE_DS))
        env.pop("SKILL_GATE", None)
        payload = {"session_id": "s1", "transcript_path": str(self.transcript), "cwd": str(self.repo),
                   "tool_name": "Edit", "tool_input": {"file_path": str(self.repo / rel_path), "new_string": "x"}}
        completed = subprocess.run([sys.executable, str(GATE), "gate"], input=json.dumps(payload),
                                   capture_output=True, text=True, env=env, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout) if completed.stdout.strip() else None

    def test_first_edit_of_a_language_in_a_root_gets_its_references_without_blocking(self):
        output = self.edit("android/app/src/main/kotlin/InvoiceList.kt")
        specific = output["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", specific, "a style hint never blocks the edit")
        self.assertIn("language-kotlin.md", specific["additionalContext"])
        self.assertIn("framework-android-compose.md", specific["additionalContext"])
        self.assertIn(str(CODE_STYLE_DS.parent.parent / "references"), specific["additionalContext"])

    def test_the_same_language_and_root_is_hinted_once_per_session(self):
        self.edit("api/billing/views.py")
        self.assertIsNone(self.edit("api/billing/models.py"))
        self.assertIn("framework-react.md", self.edit("web/app/page.tsx")["hookSpecificOutput"]["additionalContext"])


# A stand-in for the code-style runtime: the test only needs to see which install the hook picked.
STUB_STYLE_ANSWER = (
    "import json\n"
    "print(json.dumps({'language': 'python', 'root': 'api', 'repository': 'r', 'path': 'api/billing/views.py',\n"
    "                  'frameworks': ['django'], 'references': ['language-python.md'], 'style_tools': []}))\n")


def apply_patch_command(*sections):
    """The text Codex passes as tool_input.command for apply_patch."""
    return "*** Begin Patch\n" + "".join(sections) + "*** End Patch\n"


class CodexStyleHintTest(unittest.TestCase):
    """Codex edits files with apply_patch; the gate's codex-style hook adds the style references without blocking."""

    def setUp(self):
        self.home = make_temp_dir(self)
        self.repo = make_monorepo(self)
        if any(part in str(self.repo).lower() for part in ("/tmp/", "/private/tmp/")):
            self.skipTest("temp dir is on a path the gate skips by design")

    def run_hook(self, tool_name, command, session_id="c1"):
        env = dict(os.environ, HOME=str(self.home), DEVSKILLS_CODE_STYLE_DS=str(CODE_STYLE_DS))
        env.pop("SKILL_GATE", None)
        payload = {"session_id": session_id, "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                   "tool_name": tool_name, "tool_input": {"command": command}}
        completed = subprocess.run([sys.executable, str(GATE), "codex-style"], input=json.dumps(payload),
                                   capture_output=True, text=True, env=env, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout) if completed.stdout.strip() else None

    def test_patched_file_gets_its_references_without_blocking(self):
        command = apply_patch_command("*** Update File: android/app/src/main/kotlin/InvoiceList.kt\n@@\n-a\n+b\n")
        specific = self.run_hook("apply_patch", command)["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", specific, "a style hint never blocks the patch")
        self.assertIn("language-kotlin.md", specific["additionalContext"])
        self.assertIn("framework-android-compose.md", specific["additionalContext"])

    def test_every_file_of_one_patch_is_covered_once_per_root_and_language(self):
        command = apply_patch_command(
            "*** Add File: api/billing/serializers.py\n+x = 1\n",
            "*** Update File: api/billing/views.py\n@@\n-a\n+b\n",
            "*** Update File: web/app/page.tsx\n@@\n-a\n+b\n",
            "*** Delete File: web/.prettierrc\n")
        context = self.run_hook("apply_patch", command)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context.count("framework-django.md"), 1, context)
        self.assertIn("framework-react.md", context)
        self.assertIsNone(self.run_hook("apply_patch", command), "already hinted for this session")

    def test_a_moved_file_is_judged_by_its_new_path(self):
        command = apply_patch_command("*** Update File: tools/old.txt\n*** Move to: tools/report.go\n@@\n-a\n+b\n")
        self.assertIn("language-go.md", self.run_hook("apply_patch", command)["hookSpecificOutput"]["additionalContext"])

    def test_other_tools_and_non_code_files_get_nothing(self):
        self.assertIsNone(self.run_hook("Bash", "sed -i s/a/b/ api/billing/views.py"))
        self.assertIsNone(self.run_hook("apply_patch", apply_patch_command("*** Update File: web/.prettierrc\n@@\n-a\n+b\n")))

    def test_references_come_from_the_codex_install_when_both_agents_have_the_skill(self):
        for agent_dir in (".claude", ".codex"):
            skill_dir = self.home / agent_dir / "skills" / "code-style"
            (skill_dir / "scripts").mkdir(parents=True)
            (skill_dir / "scripts" / "ds.py").write_text(STUB_STYLE_ANSWER)
        env = dict(os.environ, HOME=str(self.home))
        env.pop("DEVSKILLS_CODE_STYLE_DS", None)
        env.pop("SKILL_GATE", None)
        payload = {"session_id": "c9", "cwd": str(self.repo), "hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                   "tool_input": {"command": apply_patch_command("*** Update File: api/billing/views.py\n@@\n-a\n+b\n")}}
        completed = subprocess.run([sys.executable, str(GATE), "codex-style"], input=json.dumps(payload),
                                   capture_output=True, text=True, env=env, check=False, timeout=60)
        context = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(self.home / ".codex" / "skills" / "code-style" / "references"), context)
        self.assertNotIn(str(self.home / ".claude"), context)

    def test_state_lives_under_codex_not_claude(self):
        self.run_hook("apply_patch", apply_patch_command("*** Add File: api/billing/serializers.py\n+x = 1\n"))
        self.assertTrue((self.home / ".codex" / "state" / "skill-gate").is_dir())
        self.assertFalse((self.home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
