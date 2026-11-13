"""Baseline preservation evidence, including real offline before/after executions."""

import copy
import json
import sys
import unittest

from devskills.fsutil import current_repo_state
from devskills.runner import test_source_snapshot
from devskills.runs import start_run
from devskills.trace import evaluate_criterion
from tests._support import commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write


class PreservationTest(unittest.TestCase):
    def setUp(self):
        self.root = make_temp_dir(self)
        init_git_repo(self.root)
        write(self.root, ".gitignore", ".devskills/\n__pycache__/\n")
        write(self.root, "tests/test_total.py", "def test_total():\n    assert 2 + 2 == 4\n")
        write(self.root, "tests/helpers.py", "EXPECTED_TOTAL = 4\n")
        commit_all(self.root)
        self.baseline_run = start_run(self.root, "R1", "baseline")["run_id"]
        self.current_run = start_run(self.root, "R1", "current")["run_id"]
        self.run_dir = self.root / ".devskills/runs" / self.current_run
        state = current_repo_state(self.root)
        sources = test_source_snapshot(self.root)
        self.baseline = {
            "check_id": "tests.unit", "execution_status": "completed", "gate_result": "pass",
            "started_at": "2026-11-06T00:00:00Z", "finished_at": "2026-11-06T00:00:01Z",
            "details": {"cwd": ".", "source_state": state,
                "test_sources_before": copy.deepcopy(sources), "test_sources_after": copy.deepcopy(sources),
                "attempts": [{"exit_code": 0, "timed_out": False, "streams_complete": True,
                    "junit": {"files": ["report.xml"], "parse_errors": [], "cases": [
                        {"file": "tests/test_total.py", "classname": "", "name": "test_total", "outcome": "passed"}]}}]},
        }
        self.current = copy.deepcopy(self.baseline)
        self.current.update(started_at="2026-11-06T00:00:02Z", finished_at="2026-11-06T00:00:03Z")
        self.current["repo_state"] = copy.deepcopy(state)
        self.criterion = {"id": "KEEP-1", "text": "unchanged total", "tags": ["preservation"],
            "preservation": {"baseline_run": self.baseline_run, "baseline_check": "tests.unit",
                "baseline_state": copy.deepcopy(state)},
            "evidence": [{"test": "tests/test_total.py::test_total", "check": "tests.unit"}]}

    def evaluate(self):
        write(self.root, f".devskills/runs/{self.baseline_run}/checks/tests.unit.json", json.dumps(self.baseline))
        return evaluate_criterion(self.criterion, self.root, self.run_dir, {"tests.unit": self.current})

    def test_same_exact_test_on_identified_baseline_and_current_is_verified(self):
        self.assertEqual(self.evaluate()["status"], "verified")

    def test_missing_or_wrong_baseline_is_unverified(self):
        original = copy.deepcopy(self.criterion)
        for defect in ("missing", "no_state", "wrong_state", "branch_only", "same_run", "bad_run", "wrong_check"):
            with self.subTest(defect=defect):
                self.criterion = copy.deepcopy(original)
                baseline = self.criterion["preservation"]
                if defect == "missing":
                    self.criterion.pop("preservation")
                elif defect == "no_state":
                    baseline.pop("baseline_state")
                elif defect == "wrong_state":
                    baseline["baseline_state"]["diff_digest"] = "0" * 64
                elif defect == "branch_only":
                    baseline["baseline_state"]["head"] = "main"
                elif defect == "same_run":
                    baseline["baseline_run"] = self.current_run
                elif defect == "bad_run":
                    baseline["baseline_run"] = "../../outside"
                else:
                    baseline["baseline_check"] = "tests.missing"
                self.assertEqual(self.evaluate()["status"], "unverified")

    def test_baseline_must_contain_exact_passing_completed_test(self):
        original = copy.deepcopy(self.baseline)
        for defect in ("skipped", "wrong_name", "wrong_class", "wrong_file", "not_run", "no_report", "failed", "blocked"):
            with self.subTest(defect=defect):
                self.baseline = copy.deepcopy(original)
                case = self.baseline["details"]["attempts"][0]["junit"]["cases"][0]
                expected = "unverified"
                if defect == "skipped":
                    case["outcome"] = "skipped"
                elif defect == "wrong_name":
                    case["name"] = "test_total[another_case]"
                elif defect == "wrong_class":
                    case["classname"] = "Other"
                elif defect == "wrong_file":
                    case["file"] = "tests/test_other.py"
                elif defect == "not_run":
                    self.baseline["execution_status"] = "not_run"
                elif defect == "no_report":
                    self.baseline["details"]["attempts"][0]["junit"].pop("cases")
                else:
                    self.baseline["gate_result"] = "fail" if defect == "failed" else "blocked"
                    if defect == "failed":
                        expected = "failed"
                self.assertEqual(self.evaluate()["status"], expected)

    def test_checks_and_artifacts_cannot_replace_paired_tests(self):
        self.criterion["evidence"] = [{"check": "tests.unit"}, {"review": "looks unchanged"}]
        self.assertEqual(self.evaluate()["status"], "unverified")

    def test_untagged_preservation_block_still_enforces_baseline(self):
        self.criterion["tags"] = []
        self.criterion["preservation"].pop("baseline_state")
        self.assertEqual(self.evaluate()["status"], "unverified")

    def test_test_and_helper_hashes_must_match_and_stay_current(self):
        original = copy.deepcopy(self.current)
        for defect in ("legacy", "truncated", "changed_assertion", "changed_helper", "self_modified", "missing_test_hash"):
            with self.subTest(defect=defect):
                self.current = copy.deepcopy(original)
                details = self.current["details"]
                before = details["test_sources_before"]
                if defect == "legacy":
                    details.pop("test_sources_before")
                elif defect == "truncated":
                    before["complete"] = False
                elif defect == "missing_test_hash":
                    before["hashes"].pop("tests/test_total.py")
                else:
                    path = "tests/helpers.py" if defect == "changed_helper" else "tests/test_total.py"
                    before["hashes"][path] = "0" * 64
                if defect != "self_modified":
                    details["test_sources_after"] = copy.deepcopy(before)
                self.assertEqual(self.evaluate()["status"], "unverified")
        self.current = original
        write(self.root, "tests/test_total.py", "def test_total():\n    assert True\n")
        self.assertEqual(self.evaluate()["status"], "unverified", "editing assertions after execution invalidates proof")

    def test_baseline_must_precede_current_execution(self):
        for started in (None, "invalid", "2026-11-06T00:00:02", "2026-11-05T00:00:00Z"):
            with self.subTest(started=started):
                self.current["started_at"] = started
                self.assertEqual(self.evaluate()["status"], "unverified")

    def test_invalid_test_reference_blocks_without_crashing(self):
        self.criterion["evidence"][0]["test"] = "../outside.py::test_total"
        self.assertEqual(self.evaluate()["status"], "unverified")

    def test_baseline_symlink_cannot_read_another_directory(self):
        outside = make_temp_dir(self)
        write(outside, "run.json", "{}")
        write(outside, "checks/tests.unit.json", json.dumps(self.baseline))
        (self.run_dir.parent / "external-baseline").symlink_to(outside, target_is_directory=True)
        self.criterion["preservation"]["baseline_run"] = "external-baseline"
        self.assertEqual(self.evaluate()["status"], "unverified")

    def test_current_failure_remains_failed(self):
        self.current["gate_result"] = "fail"
        self.assertEqual(self.evaluate()["status"], "failed")

    def test_code_changed_since_current_check_is_unverified(self):
        write(self.root, "pricing.py", "def total():\n    return 999\n")
        self.assertEqual(self.evaluate()["status"], "unverified")

    def test_new_test_files_do_not_invalidate_unchanged_baseline_tests(self):
        write(self.root, "tests/test_new_case.py", "def test_new_case():\n    assert True\n")
        self.current["repo_state"] = current_repo_state(self.root)
        sources = test_source_snapshot(self.root)
        self.current["details"]["test_sources_before"] = copy.deepcopy(sources)
        self.current["details"]["test_sources_after"] = copy.deepcopy(sources)
        self.assertEqual(self.evaluate()["status"], "verified")

    def test_bugfix_regression_does_not_require_passing_baseline(self):
        self.criterion.pop("preservation")
        self.criterion["tags"] = ["regression"]
        self.baseline["gate_result"] = "fail"
        self.assertEqual(self.evaluate()["status"], "verified")

    def test_real_runner_before_after_and_changed_expectation(self):
        write(self.root, "pricing.py", "def total():\n    return sum([8, 12])\n")
        test_source = '''import sys
import unittest
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing import total
class Totals(unittest.TestCase):
    def test_total(self):
        self.assertEqual(total(), 20)
if __name__ == "__main__":
    result = unittest.TextTestRunner().run(unittest.TestSuite([Totals("test_total")]))
    suite = Element("testsuite")
    case = SubElement(suite, "testcase", file="tests/test_total.py", classname="Totals", name="test_total")
    if not result.wasSuccessful():
        SubElement(case, "failure")
    ElementTree(suite).write(".devskills/report.xml", encoding="unicode")
    sys.exit(0 if result.wasSuccessful() else 1)
'''
        write(self.root, "tests/test_total.py", test_source)
        args = ("run-tests", "--repo", str(self.root), "--junit", ".devskills/report.xml")

        def execute(run_id):
            completed = run_cli(*args, "--run", run_id, "--json", "--", sys.executable, "tests/test_total.py")
            return completed.returncode, json.loads(completed.stdout)

        code, baseline = execute(self.baseline_run)
        self.assertEqual(code, 0, baseline)
        self.criterion["preservation"]["baseline_state"] = baseline["details"]["source_state"]
        self.criterion["evidence"][0]["test"] = "tests/test_total.py::Totals::test_total"
        path = write(self.root, "acceptance.json", json.dumps({"criteria": [self.criterion]}))
        write(self.root, "pricing.py", "def total():\n    first, second = 8, 12\n    return first + second\n")
        code, current = execute(self.current_run)
        self.assertEqual(code, 0, current)
        code, payload = run_cli_json("trace", "--repo", str(self.root), "--run", self.current_run, "--file", str(path))
        self.assertEqual((code, payload["gate_result"]), (0, "pass"), payload)
        # Both executions pass, but the new expectation accepts a changed result.
        write(self.root, "pricing.py", "def total():\n    return 999\n")
        write(self.root, "tests/test_total.py", test_source.replace("total(), 20", "total(), 999"))
        code, current = execute(self.current_run)
        self.assertEqual(code, 0, current)
        code, payload = run_cli_json("trace", "--repo", str(self.root), "--run", self.current_run, "--file", str(path))
        self.assertEqual((code, payload["gate_result"]), (4, "blocked"), payload)


if __name__ == "__main__":
    unittest.main()
