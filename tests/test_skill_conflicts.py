"""Skills never compete for the same step: ambiguous keywords route to one owner, one plan per task,
and the rules two skills share say the same thing."""

import importlib.util
import unittest

from tests._support import REPO_ROOT

GATE = REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py"
spec = importlib.util.spec_from_file_location("skill_gate_conflicts", GATE)
skill_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill_gate)

SP = "superpowers:"


def needs(prompt):
    return skill_gate.skills_for_request(skill_gate.route_prompt(prompt), True)


def skill_text(name):
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


class AmbiguousKeywordTest(unittest.TestCase):
    """A word with two meanings routes by the phrase around it, not by the word alone."""

    CASES = [
        # (prompt, must include, must not include)
        ("refactor gộp code trùng lặp trong utils", ["write-maintainable-code"], ["design-reliability"]),
        ("sửa gửi trùng khi mất mạng", ["design-reliability"], ["design-api"]),
        ("sửa webhook gửi trùng", ["design-api", "design-reliability"], []),
        ("sửa lỗi tạo trùng đơn hàng khi bấm 2 lần", ["design-reliability"], []),
        ("review giao diện màn hình lịch", ["verify-ui"], ["review-code", "implement-frontend"]),
        ("review UI và xem diff", ["verify-ui", "review-code"], ["implement-frontend"]),
        ("review PR #12 giúp tôi", ["review-code"], ["verify-ui"]),
        ("chụp màn hình trang chủ xem có vỡ layout ko", ["verify-ui"], ["e2e-evidence"]),
        ("viết test e2e playwright cho form lịch", ["test-safely"], ["e2e-evidence", "verify-ui", "implement-frontend"]),
        ("chạy e2e UI", ["e2e-evidence", "test-safely", "verify-ui"], ["implement-frontend"]),
        ("chạy test e2e theo checklist cho no63_5", ["e2e-evidence", "test-safely"], []),
        ("chụp màn hình từng step cho no63_5", ["e2e-evidence"], []),
        ("thêm index tài liệu dự án", ["index-project-knowledge"], ["change-database"]),
        ("thêm index cho bảng orders", ["change-database"], []),
        ("xóa icon ở menu", ["implement-frontend", "verify-ui"], ["change-database"]),
        ("đọc spec plan.html", ["index-project-knowledge"], ["task-spec", "design-change", SP + "writing-plans"]),
        ("đọc code", ["discover-codebase"], ["write-maintainable-code", "code-style"]),
    ]

    def test_each_phrase_routes_to_its_owner(self):
        for prompt, included, excluded in self.CASES:
            with self.subTest(prompt=prompt):
                for variant in (prompt, skill_gate.fold(prompt)):
                    required = needs(variant)
                    self.assertTrue(skill_gate.route_prompt(variant)["work"])
                    for skill in included:
                        self.assertIn(skill, required)
                    for skill in excluded:
                        self.assertNotIn(skill, required)


class OnePlanPerTaskTest(unittest.TestCase):
    """task-spec's plan.html is the ticket's only plan; superpowers' plan/design files would be a second one."""

    def test_a_ticket_plan_is_owned_by_task_spec(self):
        for prompt in ("lên plan cho ticket no63_5", "tạo spec cho tính năng mới no70"):
            with self.subTest(prompt=prompt):
                required = needs(prompt)
                self.assertIn("task-spec", required)
                self.assertNotIn(SP + "writing-plans", required)
                self.assertNotIn(SP + "brainstorming", required)

    def test_a_plan_without_a_ticket_keeps_the_superpowers_process(self):
        required = needs("lên kế hoạch triển khai bản iOS")
        self.assertIn("design-change", required)
        self.assertIn(SP + "writing-plans", required)
        self.assertNotIn(SP + "test-driven-development", required)
        self.assertNotIn("verify-ui", required)

    def test_future_e2e_in_a_ticket_spec_does_not_route_an_e2e_run(self):
        required = needs("viết spec cho API có test E2E")
        self.assertIn("task-spec", required)
        self.assertIn("design-api", required)
        self.assertNotIn("e2e-evidence", required)
        self.assertNotIn(SP + "test-driven-development", required)

    def test_router_names_one_plan_document_and_the_order_with_superpowers(self):
        text = skill_text("dev-orchestrate")
        self.assertIn("(ROUTE-002)", text)
        rule = text.split("(ROUTE-002)", 1)[1].split("\n## ", 1)[0]
        for phrase in ("superpowers", "brainstorming", "writing-plans", "plan.html", "docs/superpowers"):
            self.assertIn(phrase, rule)


class FixDuringE2ETest(unittest.TestCase):
    """verify-ui fixes in-scope layout regressions during implementation; e2e-evidence must allow the same."""

    def test_e2e_evidence_defers_to_fe_010_during_implementation(self):
        text = skill_text("e2e-evidence")
        rule = text.split("- E2E-008", 1)[1].split("\n- E2E-009", 1)[0]
        self.assertIn("FE-010", rule)
        self.assertIn("new run", rule)
        self.assertIn("FE-010", skill_text("verify-ui"))


if __name__ == "__main__":
    unittest.main()
