"""Documentation guidance for new code and its hand-off to maintenance."""

import importlib.util
import re
import unittest

from tests._support import REPO_ROOT

SKILL_DIR = REPO_ROOT / "skills" / "code-documentation"
# The kinds of code the skill covers; each needs an example and its rules in references/categories.md.
CATEGORIES = ("Class / interface", "Method / function", "Complex logic", "Constants / config", "Database / model",
              "API endpoint", "Background job / event", "Security / performance")
RULE_IDS = ("DOC-007", "DOC-008", "DOC-009", "DOC-010", "DOC-011", "DOC-012")


def read(path):
    return path.read_text(encoding="utf-8")


def load_gate():
    spec = importlib.util.spec_from_file_location("skill_gate", REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


class CodeDocumentationSkillTest(unittest.TestCase):
    def test_every_rule_id_is_stated_in_the_skill(self):
        text = read(SKILL_DIR / "SKILL.md")
        for rule_id in RULE_IDS:
            self.assertIn(f"({rule_id})", text, f"{rule_id} has no section in SKILL.md")

    def test_every_category_has_an_example_in_the_reference(self):
        categories = read(SKILL_DIR / "references" / "categories.md")
        for number, category in enumerate(CATEGORIES, start=1):
            section = categories.split(f"## {number}. {category}", 1)
            self.assertEqual(len(section), 2, f"missing section: {number}. {category}")
            body = section[1].split("\n## ", 1)[0]
            self.assertIn("```", body, f"{category} has no example")

    def test_documentation_is_automatic_for_new_code_only(self):
        skill = read(SKILL_DIR / "SKILL.md")
        rule = skill.split("(DOC-008)", 1)[1].split("\n## ", 1)[0]
        self.assertIn("new declarations and non-obvious new logic", rule)
        self.assertIn("including additions within an existing file", rule)
        self.assertIn("when the user explicitly asks to add comments or docstrings", rule.casefold())
        self.assertIn("including existing code", rule)
        self.assertIn("within the requested scope", rule)

    def test_maintenance_leaves_comments_alone_unless_the_change_makes_them_wrong(self):
        maintenance = read(REPO_ROOT / "skills" / "write-maintainable-code" / "SKILL.md")
        self.assertIn("When your change makes an existing comment inaccurate", maintenance)
        self.assertIn("even when it sits outside the changed lines", maintenance)
        self.assertIn("only when the user requests it", maintenance)

    def test_new_code_has_handoffs_from_maintainability_and_style(self):
        maintenance = read(REPO_ROOT / "skills" / "write-maintainable-code" / "SKILL.md")
        self.assertIn("write-maintainable-code", read(SKILL_DIR / "SKILL.md"))
        self.assertIn("load code-documentation if available", maintenance.casefold())
        self.assertIn("code-documentation", read(REPO_ROOT / "skills" / "code-style" / "SKILL.md"))

    def test_specialist_is_discoverable_and_has_no_blocking_edit_requirement(self):
        orchestrate = read(REPO_ROOT / "skills" / "dev-orchestrate" / "SKILL.md")
        self.assertIn("load code-documentation for new code", orchestrate)
        self.assertIn("code-documentation for new code", read(REPO_ROOT / "skills" / "review-code" / "SKILL.md"))
        gate = load_gate()
        self.assertNotIn("code-documentation", gate.BASE_EDIT)
        self.assertIn("code-documentation", gate.ALL_SKILLS)

    def test_doc_comment_request_routes_to_general_maintainability(self):
        gate = load_gate()
        route = gate.route_prompt("thêm docstring cho các hàm trong utils")
        self.assertEqual(route["areas"], ["write-maintainable-code"])
        self.assertNotIn("code-documentation", gate.skills_for_request(route))

    def test_description_fits_the_listing_budget_and_has_vietnamese_triggers(self):
        description = re.search(r'^description: "(.*)"$', read(SKILL_DIR / "SKILL.md"), re.M).group(1)
        self.assertTrue(description.startswith("Use when"))
        self.assertIn("Triggers (vi):", description)
        self.assertLessEqual(len(description), 600)


if __name__ == "__main__":
    unittest.main()
