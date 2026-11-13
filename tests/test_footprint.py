"""footprint: new vs existing code touched, protected paths, edited migrations, scope and formatting signals."""

import unittest

from devskills.footprint import glob_to_regex
from devskills.runs import build_default_roster
from tests._support import commit_all, git, init_git_repo, make_temp_dir, run_cli_json, write

CALCULATOR = "class BookingAmountCalculator:\n" + "".join(f"    def step_{index}(self):\n        return {index}\n" for index in range(60))


class GlobTest(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(glob_to_regex("billing/**").match("billing/a/b.py"))
        self.assertTrue(glob_to_regex("app/Services/Pdf/").match("app/Services/Pdf/X.php"))
        self.assertTrue(glob_to_regex("**/*Calculator.php").match("app/Services/Booking/BookingAmountCalculator.php"))
        self.assertTrue(glob_to_regex("**/*Calculator.php").match("Calculator.php"))
        self.assertFalse(glob_to_regex("app/*.py").match("app/sub/x.py"))


class FootprintCliTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_dir(self)
        init_git_repo(self.repo)
        write(self.repo, "billing/calculator.py", CALCULATOR)
        write(self.repo, "orders/service.py", "def create_order():\n    return 1\n")
        write(self.repo, "orders/migrations/0001_initial.py", "operations = []\n")
        commit_all(self.repo)
        git(self.repo, "checkout", "-q", "-b", "feature")

    def footprint(self, *extra):
        return run_cli_json("footprint", "--repo", str(self.repo), "--base", "main", *extra)

    def test_new_code_beside_running_logic_passes(self):
        write(self.repo, "billing/pricing_v2.py", "def calculate(booking):\n    return 2\n")
        write(self.repo, "billing/tests/test_pricing_v2.py", "def test_x():\n    assert True\n")
        commit_all(self.repo, "add v2")
        code, payload = self.footprint("--scope", "billing/**")
        self.assertEqual((code, payload["gate_result"]), (0, "pass"), payload["findings"])
        totals = payload["details"]["totals"]
        self.assertEqual((totals["new_code"]["files"], totals["existing_code"]["files"]), (1, 0))
        self.assertEqual(totals["tests_and_generated"]["files"], 1)

    def test_protected_path_and_migration_edit_fail_until_approved(self):
        write(self.repo, ".devskills.toml", "[change]\nprotected_paths = ['billing/**']\n")
        write(self.repo, "billing/calculator.py", CALCULATOR.replace("return 3\n", "return 33\n"))
        write(self.repo, "orders/migrations/0001_initial.py", "operations = ['x']\n")
        code, payload = self.footprint()
        self.assertEqual((code, payload["gate_result"]), (3, "fail"))
        rules = {finding["rule_id"] for finding in payload["findings"]}
        self.assertTrue({"FOOT-PROTECTED", "FOOT-MIGRATION-EDITED"} <= rules, rules)
        git(self.repo, "checkout", "-q", "--", "orders/migrations/0001_initial.py")
        _, payload = self.footprint("--allow-protected", "billing/calculator.py")
        self.assertNotIn("FOOT-PROTECTED", {finding["rule_id"] for finding in payload["findings"]})

    def test_rewrite_out_of_scope_formatting_and_deletion(self):
        write(self.repo, "billing/calculator.py", "class BookingAmountCalculator:\n    pass\n")
        write(self.repo, "orders/service.py", "def create_order():\n\n    return 1\n")
        commit_all(self.repo, "rewrite")
        git(self.repo, "rm", "-q", "orders/migrations/0001_initial.py")
        _code, payload = self.footprint("--scope", "billing/**")
        by_rule = {}
        for finding in payload["findings"]:
            by_rule.setdefault(finding["rule_id"], set()).add(finding["path"])
        self.assertEqual(by_rule["FOOT-LARGE-EDIT"], {"billing/calculator.py"})
        self.assertEqual(by_rule["FOOT-FORMAT-ONLY"], {"orders/service.py"})
        self.assertIn("orders/service.py", by_rule["FOOT-OUT-OF-SCOPE"])
        self.assertIn("orders/migrations/0001_initial.py", by_rule["FOOT-MIGRATION-EDITED"])
        self.assertEqual(payload["gate_result"], "fail")

    def test_blocked_without_history(self):
        empty = make_temp_dir(self)
        init_git_repo(empty)
        _code, payload = run_cli_json("footprint", "--repo", str(empty))
        self.assertEqual(payload["gate_result"], "blocked")


class RosterTest(unittest.TestCase):
    def test_footprint_expected_for_code_changes_from_r1(self):
        self.assertIn("change.footprint", {item["check_id"] for item in build_default_roster("R1", {"code"})})
        self.assertNotIn("change.footprint", {item["check_id"] for item in build_default_roster("R0", {"code"})})
        self.assertNotIn("change.footprint", {item["check_id"] for item in build_default_roster("R2", {"docs"})})


if __name__ == "__main__":
    unittest.main()
