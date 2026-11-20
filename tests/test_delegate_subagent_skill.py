"""Delegating new material and independent runs to subagents so the main context stays small."""

import importlib.util
import json
import unittest

from tests._support import REPO_ROOT

SKILL_DIR = REPO_ROOT / "skills" / "delegate-subagent"
RULE_IDS = ("DLG-001", "DLG-002", "DLG-003", "DLG-004", "DLG-005")
# Brief templates per kind of work; each ends with a return contract.
TEMPLATES = ("Read and summarize a document", "Trace a part of the source code", "Mechanical search or extraction",
             "Independent run in the background")


def read(path):
    return path.read_text(encoding="utf-8")


def rule_text(rule_id):
    """The section whose heading ends with the rule id (the id also appears inside tables)."""
    return read(SKILL_DIR / "SKILL.md").split(f"({rule_id})\n", 1)[1].split("\n## ", 1)[0]


def load_gate():
    spec = importlib.util.spec_from_file_location("skill_gate_delegate", REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


class DelegateSubagentSkillTest(unittest.TestCase):
    def test_every_rule_id_is_stated_in_the_skill(self):
        text = read(SKILL_DIR / "SKILL.md")
        for rule_id in RULE_IDS:
            self.assertIn(f"({rule_id})\n", text, f"{rule_id} has no section in SKILL.md")

    def test_routing_keeps_known_material_and_approvals_in_the_main_thread(self):
        table = rule_text("DLG-001")
        self.assertIn("Material already read into this session", table)
        self.assertIn("A file the request only names, not yet opened, is new material", table)
        self.assertIn("never re-read it through a subagent", table)
        self.assertIn("needs the user's approval", table)
        self.assertIn("one writer per file", table)
        self.assertIn("no subagent tool", table, "hosts without subagents get a fallback")

    def test_new_material_and_independent_runs_go_to_the_smallest_model(self):
        table = rule_text("DLG-001")
        rows = {line.split("|")[1].strip()[:30]: line for line in table.splitlines() if line.startswith("| ")}
        new_material = next(line for key, line in rows.items() if key.startswith("A new document"))
        self.assertTrue(new_material.rstrip(" |").endswith("sonnet"))
        mechanical = next(line for key, line in rows.items() if key.startswith("Mechanical search"))
        self.assertIn("haiku, effort high", mechanical)
        independent = next(line for key, line in rows.items() if key.startswith("Independent long-running"))
        self.assertIn("background subagent", independent)
        self.assertIn("Escalate once, do not loop", rule_text("DLG-002"))

    def test_brief_has_goal_inputs_scope_safety_and_return_contract(self):
        brief = rule_text("DLG-003")
        for part in ("**Goal**", "**Inputs**", "**Scope**", "**Safety**", "**Return contract**"):
            self.assertIn(part, brief)
        self.assertIn("do not inherit loaded skills", brief)
        self.assertIn("do not hand over your hypothesis", brief)

    def test_every_template_has_a_return_contract(self):
        templates = read(SKILL_DIR / "references" / "brief-templates.md")
        for number, title in enumerate(TEMPLATES, start=1):
            section = templates.split(f"## {number}. {title}", 1)
            self.assertEqual(len(section), 2, f"missing template: {number}. {title}")
            body = section[1].split("\n## ", 1)[0]
            self.assertIn("Return", body, f"{title} has no return contract")
            self.assertIn("Scope", body, f"{title} has no scope")

    def test_results_are_verified_and_never_invented(self):
        self.assertIn("never state a result that has not arrived", rule_text("DLG-004"))
        self.assertIn("never one subagent per item", rule_text("DLG-004"))
        taking_back = rule_text("DLG-005")
        self.assertIn("open the cited source", taking_back)
        self.assertIn("name what was delegated", taking_back)


class DelegateSubagentRoutingTest(unittest.TestCase):
    def test_router_rules_and_gate_point_to_the_skill(self):
        self.assertIn("delegate-subagent", read(REPO_ROOT / "skills" / "dev-orchestrate" / "SKILL.md"))
        self.assertIn("delegate-subagent", read(REPO_ROOT / "tools" / "agent-rules.md"))
        gate = load_gate()
        self.assertIn("delegate-subagent", gate.ALL_SKILLS)
        self.assertIn("delegate-subagent", gate.RULE)

    def test_read_only_subagents_are_not_told_to_load_skills(self):
        source = read(REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py")
        hook = source.split("def cmd_subagent", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("A read-only task", hook)
        self.assertIn("needs none", hook)

    def test_requests_that_read_new_material_or_run_in_parallel_get_the_hint(self):
        gate = load_gate()
        delegating = ("Đọc toàn bộ folder deploy/evidence/no63_5 rồi tóm tắt case nào OK, case nào NG",
                      "Tìm mọi chỗ dùng isDailyRateApplied trong source",
                      "Chạy unit test ở nền, trong lúc đó giải thích Edit.tsx",
                      "Đọc file spec Excel của khách rồi đối chiếu",
                      "summarize the docs folder", "run the builds in parallel",
                      "dùng subagent: kiểm tra log", "dùng delegate: kiểm tra log",
                      "đối chiếu toàn bộ specs/TASK-*.md với code hiện tại",
                      "kiểm tra tất cả màn hình có dùng 備品")
        for prompt in delegating:
            with self.subTest(prompt=prompt):
                self.assertTrue(gate.route_prompt(prompt)["delegation"])
        for prompt in ("sửa lỗi nút lưu ở màn hình lịch", "có nên dùng redis không?", "đọc code Edit.tsx", "review PR #12"):
            with self.subTest(prompt=prompt):
                self.assertFalse(gate.route_prompt(prompt)["delegation"])
        self.assertIn("load delegate-subagent", gate.DELEGATION_HINT)

    def test_the_skill_is_required_first_so_it_is_loaded_before_reading(self):
        gate = load_gate()
        prompt = ("1. đọc specs/デルマール料金マスタ.md, liệt kê các loại 料金\n"
                  "2. đọc deploy/evidence/no63_5, cho biết case nào OK, case nào NG")
        route = gate.route_prompt(prompt)
        self.assertEqual(route["areas"][0], "delegate-subagent")
        required = gate.skills_for_request(route, False)
        self.assertEqual(required[:2], ["dev-orchestrate", "delegate-subagent"])
        rule = rule_text("DLG-001")
        self.assertLess(rule.index("First, count the independent tasks"), rule.index("| Work |"),
                        "the multi-task check must come before the size rows")
        self.assertIn("apply only to a request with a single task", rule)
        self.assertIn("one subagent per task", gate.DELEGATION_HINT)

    def test_an_eval_scenario_covers_the_skill(self):
        scenarios = json.loads(read(REPO_ROOT / "evals" / "scenarios.json"))["scenarios"]
        self.assertTrue(any(item["skill"] == "delegate-subagent" for item in scenarios))


if __name__ == "__main__":
    unittest.main()
