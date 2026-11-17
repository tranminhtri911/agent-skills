"""Skill gate (tools/skill-gate/skill-gate.py): skills are routed by what the work is, not by file names."""

import importlib.util
import json
import os
import subprocess
import sys
import unittest

from tests._support import REPO_ROOT, make_temp_dir, write

GATE = REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py"
spec = importlib.util.spec_from_file_location("skill_gate", GATE)
skill_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill_gate)

BASE = ["dev-orchestrate", "discover-codebase", "write-maintainable-code", "code-style"]
SP = "superpowers:"


def needs(prompt, superpowers=True):
    return skill_gate.skills_for_request(skill_gate.route_prompt(prompt), superpowers)


class PromptRoutingTest(unittest.TestCase):
    """Real requests (several from the lich_am sessions) and the skills their work touches."""

    CASES = [
        # (prompt, must include, must not include)
        ("có thể thêm chức năng backup lên google driver ko ?",
         ["change-database", "design-reliability", "design-change", SP + "brainstorming", SP + "test-driven-development",
          "write-maintainable-code", "test-safely", SP + "verification-before-completion"], [SP + "systematic-debugging"]),
        ("Xóa các khảo sát test khỏi danh sách kết quả", ["change-database", "dev-orchestrate"], []),
        ("vi sao cai app-realease-unsigned.apk ko đc?",
         ["implement-frontend", SP + "systematic-debugging"], [SP + "brainstorming"]),
        ("trong app android làm sao cho hiển thị ngày ở lockscreen?", ["implement-frontend", "verify-ui"], []),
        ("riêng phần setting thông báo nên có trên bản web, app", ["implement-frontend", "design-reliability"], []),
        ("thêm các điều khoản, chính sách bảo mật, giới thiệu nhiều vào", ["implement-frontend"], ["review-security"]),
        ("thêm API đăng nhập bằng token", ["design-api", "implement-backend", "review-security"], []),
        ("review PR #12 giúp tôi", ["review-code"], [SP + "test-driven-development", "write-maintainable-code"]),
        ("lên kế hoạch triển khai bản iOS", ["design-change", SP + "writing-plans", "implement-frontend"], []),
        ("sửa theo góp ý của codex review", [SP + "receiving-code-review"], []),
        ("trang danh sách tải chậm quá, tối ưu giúp", ["review-performance", "change-database", "implement-frontend"], []),
        ("viết test e2e cho màn hình lịch", ["test-safely", "implement-frontend"], []),
        ("tạo VPC và RDS bằng terraform", ["design-infrastructure"], []),
    ]

    def test_requests_route_to_the_skills_their_work_touches(self):
        for prompt, included, excluded in self.CASES:
            required = needs(prompt)
            for skill in included:
                self.assertIn(skill, required, f"{prompt!r} should need {skill}; got {required}")
            for skill in excluded:
                self.assertNotIn(skill, required, f"{prompt!r} should not need {skill}; got {required}")

    def test_questions_and_chat_require_nothing(self):
        for prompt in ("vì sao claude dùng ít skills vậy", "ok bỏ đi", "cùng 1 session thì ko cần đúng ko"):
            self.assertEqual(needs(prompt), [], prompt)

    PASTED_CHECKLIST = (
        '<pasted_content id="b419">\nChecklist: sửa chính sách Foreign Key trong database, bổ sung sandbox '
        'bảo mật, viết test cho Terraform, React, thanh toán; hãy kiểm tra lỗi sai trước khi thay đổi.\n'
        '</pasted_content id="b419">'
    )

    def test_pasted_text_does_not_route_the_users_own_question(self):
        # A pasted checklist names many areas; the user only asked whether it was done.
        self.assertEqual(needs("\n\n" + self.PASTED_CHECKLIST + "\n\ncheck xem đã sửa chưa"), [])

    def test_pasted_text_is_routed_when_the_user_wrote_nothing_else(self):
        required = needs('<pasted_content id="x1">\nthêm API đăng nhập bằng token\n</pasted_content id="x1">')
        self.assertIn("design-api", required)
        self.assertIn("review-security", required)

    def test_accents_and_typing_without_accents_route_the_same(self):
        self.assertEqual(needs("xóa dữ liệu khách hàng"), needs("xoa du lieu khach hang"))

    def test_superpowers_are_required_only_when_the_plugin_is_enabled(self):
        self.assertFalse([s for s in needs("sửa lỗi crash khi lưu dữ liệu", superpowers=False) if s.startswith(SP)])
        self.assertIn(SP + "systematic-debugging", needs("sửa lỗi crash khi lưu dữ liệu", superpowers=True))

    def test_additional_domain_phrases_match_with_and_without_accents(self):
        cases = [
            ("sửa khóa bản ghi", "change-database"),
            ("sửa response body", "design-api"),
            ("sửa nghiệp vụ", "implement-backend"),
            ("sửa vỡ layout và xuống dòng", "implement-frontend"),
            ("sửa gửi trùng khi mất mạng", "design-reliability"),
            ("thêm xác thực", "review-security"),
            ("sửa rò rỉ bộ nhớ", "review-performance"),
            ("tái hiện lỗi", "test-safely"),
            ("đề xuất giải pháp", "design-change"),
            ("kiểm tra code trước khi bàn giao", "review-code"),
            ("cập nhật knowledge index", "index-project-knowledge"),
            ("sửa security group", "design-infrastructure"),
        ]
        for prompt, skill in cases:
            with self.subTest(prompt=prompt):
                route = skill_gate.route_prompt(prompt)
                self.assertIn(skill, route["areas"])
                self.assertTrue(route["work"])
                self.assertEqual(route, skill_gate.route_prompt(skill_gate.fold(prompt)))

    def test_new_phrases_keep_word_boundaries_and_question_handling(self):
        for prompt in ("sửa rebucketed", "sửa controllerish", "sửa reprojection"):
            with self.subTest(prompt=prompt):
                self.assertEqual(skill_gate.route_prompt(prompt)["areas"], [])
        for prompt in ("response body là gì?", "knowledge index để làm gì?", "xác thực là gì?"):
            with self.subTest(prompt=prompt):
                self.assertFalse(skill_gate.route_prompt(prompt)["work"])


class EditAndCommandRoutingTest(unittest.TestCase):
    def test_a_code_edit_needs_the_base_skills_plus_what_the_request_touches(self):
        self.assertEqual(skill_gate.required_for("/p/src/pricing.py"), BASE)
        task = ["change-database", "verify-ui", SP + "verification-before-completion"]
        required = skill_gate.required_for("/p/src/pricing.py", task)
        self.assertIn("change-database", required)
        self.assertNotIn("verify-ui", required, "after-work skills are not needed before the first edit")

    def test_routing_never_depends_on_class_names_or_file_contents(self):
        # Same request, very different files: same requirement.
        task = ["implement-frontend"]
        self.assertEqual(skill_gate.required_for("/p/android/data/EventDao.kt", task),
                         skill_gate.required_for("/p/web/app/page.tsx", task))

    def test_commands_are_routed_by_what_they_do(self):
        route = skill_gate.required_for_command
        for command in ("npm run test", "python3 -m pytest -q", "./gradlew :app:testDebugUnitTest", "npx vitest run"):
            self.assertIn("test-safely", route(command), command)
        self.assertIn("change-database", route("psql -h localhost -c 'select 1'"))
        self.assertIn("change-database", route("python manage.py migrate"))
        self.assertIn("review-code", route("git commit -m 'feat: x'"))
        self.assertIn("write-maintainable-code", route("cat > /p/web/app/page.tsx <<'EOF'"))
        for harmless in ("ls -la", "git status", "rg foo", "cat README.md"):
            self.assertEqual(route(harmless), [], harmless)


class SkillDescriptionTest(unittest.TestCase):
    """Descriptions are what Claude matches a request against; Vietnamese prompts need Vietnamese triggers."""

    def test_every_skill_lists_vietnamese_triggers_within_the_listing_budget(self):
        import re
        for path in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
            description = re.search(r'^description: "(.*)"$', path.read_text(encoding="utf-8"), re.M).group(1)
            description = description.replace('\\"', '"')
            self.assertIn("Triggers (vi):", description, path.parent.name)
            self.assertIn("làm sao", description, f"{path.parent.name}: question-phrased requests must trigger too")
            self.assertLessEqual(len(description), 600, f"{path.parent.name}: the tail (Vietnamese triggers) gets truncated")


class HookEndToEndTest(unittest.TestCase):
    """The installed command run as Claude Code runs it: JSON on stdin, decision on stdout."""

    def setUp(self):
        self.home = make_temp_dir(self)
        self.transcript = write(self.home, "session.jsonl", "")
        self.base = {"session_id": "s1", "transcript_path": str(self.transcript)}

    def enable_superpowers(self, enabled):
        write(self.home, ".claude/settings.json",
              json.dumps({"enabledPlugins": {"superpowers@claude-plugins-official": enabled}}))

    def hook(self, sub, **payload):
        env = dict(os.environ, HOME=str(self.home))
        env.pop("SKILL_GATE", None)
        completed = subprocess.run([sys.executable, str(GATE), sub], input=json.dumps(dict(self.base, **payload)),
                                   capture_output=True, text=True, env=env, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout) if completed.stdout.strip() else None

    def load(self, *skills):
        with self.transcript.open("a") as handle:
            for skill in skills:
                handle.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]}}) + "\n")

    def say(self, text):
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")

    def test_request_is_routed_and_finishing_without_its_skills_is_blocked_once(self):
        self.enable_superpowers(True)
        context = self.hook("prompt", prompt="Xóa các khảo sát test khỏi danh sách kết quả")
        text = context["hookSpecificOutput"]["additionalContext"]
        self.assertIn("change-database", text)
        self.assertIn(SP + "test-driven-development", text)

        self.say("Done.")
        blocked = self.hook("stop")
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("change-database", blocked["reason"])
        self.assertIsNone(self.hook("stop", stop_hook_active=True), "never blocks twice in a row")

        self.load("dev-orchestrate", "discover-codebase", "change-database", "test-safely", "write-maintainable-code",
                  "code-style", "review-code", SP + "test-driven-development", SP + "verification-before-completion")
        self.assertIsNone(self.hook("stop"), "allowed once the request's skills are loaded")

    def test_follow_up_without_an_area_keeps_the_previous_request(self):
        self.enable_superpowers(False)
        self.hook("prompt", prompt="thêm API xuất báo cáo doanh thu")
        self.hook("prompt", prompt="ok làm đi")
        self.say("Done.")
        blocked = self.hook("stop")
        self.assertIsNotNone(blocked)
        self.assertIn("design-api", blocked["reason"])
        self.assertNotIn(SP, blocked["reason"], "no superpowers requirement when the plugin is disabled")

    def test_a_question_never_blocks(self):
        self.enable_superpowers(True)
        self.hook("prompt", prompt="vì sao claude dùng ít skills vậy")
        self.say("Because ...")
        self.assertIsNone(self.hook("stop"))

    def test_code_edit_is_denied_until_the_requests_skills_are_loaded(self):
        root = make_temp_dir(self)
        if any(part in str(root).lower() for part in skill_gate.SKIP_PARTS):
            self.skipTest("temp dir is on a path the gate skips by design (e.g. /tmp)")
        self.enable_superpowers(False)
        code = write(root, "app/survey_service.py", "def list_results():\n    return []\n")
        self.hook("prompt", prompt="Xóa các khảo sát test khỏi danh sách kết quả")
        self.load(*BASE)
        edit = {"tool_name": "Edit", "tool_input": {"file_path": str(code), "new_string": "x = 1"}}
        reason = self.hook("gate", **edit)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("change-database", reason, "the request, not the file, routes the database skill")
        self.assertNotIn("dev-orchestrate,", reason, "skills already loaded are not asked for again")
        self.load("change-database", "test-safely")
        self.assertIsNone(self.hook("gate", **edit))

    def test_running_tests_is_denied_until_test_safely_is_loaded(self):
        command = {"tool_name": "Bash", "tool_input": {"command": "python3 -m pytest -q"}}
        self.assertEqual(self.hook("gate", **command)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.load("dev-orchestrate", "test-safely")
        self.assertIsNone(self.hook("gate", **command))
        self.assertIsNone(self.hook("gate", tool_name="Bash", tool_input={"command": "git status"}))

    def test_skills_applied_naming_an_unloaded_skill_is_blocked(self):
        self.load("dev-orchestrate")
        self.say("Done.\n\nSkills applied: dev-orchestrate AGENT-012, change-database TX-001, superpowers:brainstorming")
        reason = self.hook("stop")["reason"]
        self.assertIn("change-database", reason)
        self.assertIn(SP + "brainstorming", reason)


if __name__ == "__main__":
    unittest.main()
