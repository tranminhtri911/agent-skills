"""code-style: per-language and per-framework style references, linked both ways with write-maintainable-code."""

import importlib.util
import re
import unittest

from tests._support import REPO_ROOT

SKILL_DIR = REPO_ROOT / "skills" / "code-style"
LANGUAGES = ("python", "typescript", "java", "kotlin", "csharp", "php", "go", "swift", "dart", "sql")
# Each framework reference points back to the language reference whose rules it builds on.
FRAMEWORK_LANGUAGE = {
    "django": "python",
    "fastapi": "python",
    "react": "typescript",
    "vue": "typescript",
    "angular": "typescript",
    "nestjs": "typescript",
    "spring": "java",
    "android-compose": "kotlin",
    "aspnet-core": "csharp",
    "laravel": "php",
    "swiftui": "swift",
    "flutter": "dart",
}
RULE_IDS = [f"STYLE-{number:03d}" for number in range(1, 8)]


def read(path):
    return path.read_text(encoding="utf-8")


def reference(name):
    return SKILL_DIR / "references" / f"{name}.md"


class CodeStyleSkillTest(unittest.TestCase):
    def test_skill_states_every_style_rule(self):
        skill = read(SKILL_DIR / "SKILL.md")
        for rule_id in RULE_IDS:
            self.assertIn(rule_id, skill)

    def test_skill_links_every_language_and_framework_reference(self):
        skill = read(SKILL_DIR / "SKILL.md")
        names = ["patterns"] + [f"language-{language}" for language in LANGUAGES]
        names += [f"framework-{framework}" for framework in FRAMEWORK_LANGUAGE]
        for name in names:
            self.assertTrue(reference(name).is_file(), f"missing references/{name}.md")
            self.assertIn(f"(references/{name}.md)", skill, f"SKILL.md does not link {name}.md")

    def test_every_reference_cites_its_sources(self):
        for path in sorted((SKILL_DIR / "references").glob("*.md")):
            text = read(path)
            self.assertIn("## Sources", text, path.name)
            sources = text.split("## Sources", 1)[1]
            self.assertRegex(sources, r"\(https://[^)\s]+\)", f"{path.name} cites no source link")

    def test_framework_references_build_on_their_language_reference(self):
        for framework, language in FRAMEWORK_LANGUAGE.items():
            text = read(reference(f"framework-{framework}"))
            self.assertIn(f"(language-{language}.md)", text, f"framework-{framework}.md must link language-{language}.md")

    def test_language_references_point_to_their_frameworks(self):
        for framework, language in FRAMEWORK_LANGUAGE.items():
            text = read(reference(f"language-{language}"))
            self.assertIn(f"(framework-{framework}.md)", text, f"language-{language}.md must link framework-{framework}.md")

    def test_code_style_and_write_maintainable_code_reference_each_other(self):
        self.assertIn("write-maintainable-code", read(SKILL_DIR / "SKILL.md"))
        maintainable = read(REPO_ROOT / "skills" / "write-maintainable-code" / "SKILL.md")
        self.assertIn("code-style", maintainable)
        self.assertIn("code-style", read(REPO_ROOT / "skills" / "write-maintainable-code" / "references" / "patterns-and-architecture.md"))

    def test_routing_loads_code_style_with_every_code_change(self):
        orchestrate = read(REPO_ROOT / "skills" / "dev-orchestrate" / "SKILL.md")
        self.assertIn("source edits → write-maintainable-code and code-style", orchestrate)
        self.assertIn("code-style", read(REPO_ROOT / "skills" / "review-code" / "SKILL.md"))
        spec = importlib.util.spec_from_file_location("skill_gate", REPO_ROOT / "tools" / "skill-gate" / "skill-gate.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        self.assertIn("code-style", gate.BASE_EDIT)
        self.assertIn("code-style", gate.ALL_SKILLS)

    def test_description_fits_the_listing_budget_and_has_vietnamese_triggers(self):
        description = re.search(r'^description: "(.*)"$', read(SKILL_DIR / "SKILL.md"), re.M).group(1)
        self.assertTrue(description.startswith("Use when"))
        self.assertIn("Triggers (vi):", description)
        self.assertLessEqual(len(description), 600)


if __name__ == "__main__":
    unittest.main()
