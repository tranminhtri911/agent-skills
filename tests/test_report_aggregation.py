"""Gate aggregation acceptance cases from plan §26.2 (missing, duplicate, stale, waived, critical)."""

import json
import unittest

from devskills.report import aggregate
from tests._support import commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write


def result(check_id, gate, digest="d1", findings=None):
    return {"check_id": check_id, "gate_result": gate, "summary": "", "findings": findings or [],
            "repo_state": {"diff_digest": digest}}


class AggregateTest(unittest.TestCase):
    def test_all_required_pass(self):
        roster = [{"check_id": "a", "required": True}, {"check_id": "b", "required": True}]
        outcome = aggregate(roster, [result("a", "pass"), result("b", "pass")], "d1", "R1")
        self.assertEqual(outcome["overall"], "pass")

    def test_missing_required_result_blocks(self):
        roster = [{"check_id": "a", "required": True}, {"check_id": "b", "required": True}]
        outcome = aggregate(roster, [result("a", "pass")], "d1", "R1")
        self.assertEqual(outcome["overall"], "blocked")
        self.assertIn("not run", outcome["rows"][1]["detail"])

    def test_required_flag_comes_from_roster_not_from_result(self):
        roster = [{"check_id": "a", "required": True}]
        tampered = result("a", "blocked") | {"required": False}
        self.assertEqual(aggregate(roster, [tampered], "d1", "R1")["overall"], "blocked")

    def test_duplicate_results_for_one_id_block(self):
        roster = [{"check_id": "a", "required": True}]
        outcome = aggregate(roster, [result("a", "pass"), result("a", "fail")], "d1", "R1")
        self.assertEqual(outcome["overall"], "blocked")

    def test_stale_result_blocks(self):
        roster = [{"check_id": "a", "required": True}]
        outcome = aggregate(roster, [result("a", "pass", digest="old")], "new", "R1")
        self.assertEqual(outcome["overall"], "blocked")
        self.assertIn("stale", outcome["rows"][0]["detail"])

    def test_critical_finding_in_optional_check_fails_overall(self):
        roster = [{"check_id": "a", "required": True}, {"check_id": "b", "required": False}]
        critical = result("b", "warn", findings=[{"severity": "critical", "rule_id": "X", "message": "m"}])
        self.assertEqual(aggregate(roster, [result("a", "pass"), critical], "d1", "R1")["overall"], "fail")

    def test_optional_missing_is_warning_only(self):
        roster = [{"check_id": "a", "required": True}, {"check_id": "b", "required": False}]
        self.assertEqual(aggregate(roster, [result("a", "pass")], "d1", "R1")["overall"], "warn")

    def test_waived_check_is_not_applicable(self):
        roster = [{"check_id": "a", "required": True}, {"check_id": "b", "required": True, "waived": True, "waiver_reason": "no UI"}]
        outcome = aggregate(roster, [result("a", "pass")], "d1", "R1")
        self.assertEqual(outcome["overall"], "pass")
        self.assertEqual(outcome["rows"][1]["gate"], "not_applicable")

    def test_invalid_gate_value_blocks(self):
        roster = [{"check_id": "a", "required": True}]
        self.assertEqual(aggregate(roster, [result("a", "PASSED!")], "d1", "R1")["overall"], "blocked")

    def test_empty_roster_blocks_unless_r0(self):
        self.assertEqual(aggregate([], [], "d1", "R2")["overall"], "blocked")
        self.assertEqual(aggregate([], [], "d1", "R0")["overall"], "pass")

    def test_missing_roster_blocks(self):
        self.assertEqual(aggregate(None, [result("a", "pass")], "d1", "R1")["overall"], "blocked")


class RunWorkflowTest(unittest.TestCase):
    """End to end: run start → roster init → checks → report, in a real git repository."""

    def setUp(self):
        self.repo = make_temp_dir(self)
        init_git_repo(self.repo)
        write(self.repo, "app/service.py", "def total_minor(a: int, b: int) -> int:\n    return a + b\n")
        commit_all(self.repo)
        write(self.repo, "app/service.py", "def total_minor(a: int, b: int) -> int:\n    return a + b + 0\n")

    def test_report_blocks_until_required_checks_run(self):
        code, started = run_cli_json("run", "start", "--repo", str(self.repo), "--risk", "R1")
        self.assertEqual(code, 0)
        run_id = started["run_id"]
        roster = run_cli("roster", "init", "--repo", str(self.repo), "--run", run_id, "--risk", "R1")
        self.assertEqual(roster.returncode, 0, roster.stderr)
        self.assertIn("tests.unit", roster.stdout)

        report = run_cli("report", "--repo", str(self.repo), "--run", run_id)
        self.assertEqual(report.returncode, 4, report.stdout)

        for command in (["scan-secrets"], ["check-code"]):
            completed = run_cli(*command, "--repo", str(self.repo), "--run", run_id)
            self.assertIn(completed.returncode, (0, 3), completed.stdout + completed.stderr)
        waive = run_cli("roster", "waive", "security.secrets", "--repo", str(self.repo), "--run", run_id, "--reason", "x")
        self.assertEqual(waive.returncode, 2, "security.secrets must not be waivable")

        report = run_cli("report", "--repo", str(self.repo), "--run", run_id)
        self.assertEqual(report.returncode, 4, "context.map and tests.unit are still missing")
        final_report = (self.repo / ".devskills" / "runs" / run_id / "final-report.md").read_text(encoding="utf-8")
        self.assertIn("| tests.unit | yes | blocked |", final_report)
        self.assertTrue((self.repo / ".devskills" / ".gitignore").is_file())
        status = run_cli("run", "show", "--repo", str(self.repo), "--run", run_id)
        self.assertEqual(json.loads(status.stdout)["risk"], "R1")

    def test_stale_evidence_after_new_edit(self):
        _code, started = run_cli_json("run", "start", "--repo", str(self.repo), "--risk", "R0")
        run_id = started["run_id"]
        run_cli("roster", "init", "--repo", str(self.repo), "--run", run_id, "--risk", "R0")
        run_cli("scan-secrets", "--repo", str(self.repo), "--run", run_id)
        run_cli("check-code", "--repo", str(self.repo), "--run", run_id)
        first = run_cli("report", "--repo", str(self.repo), "--run", run_id)
        self.assertEqual(first.returncode, 0, first.stdout)
        write(self.repo, "app/service.py", "def total_minor(a: int, b: int) -> int:\n    return b + a\n")
        second = run_cli("report", "--repo", str(self.repo), "--run", run_id)
        self.assertEqual(second.returncode, 4, second.stdout)
        self.assertIn("stale", second.stdout)


if __name__ == "__main__":
    unittest.main()
