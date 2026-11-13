"""run-tests end to end with real child processes: env allowlist, timeouts, network guard, reports."""

import json
import os
import sys
import time
import unittest
from pathlib import Path

from devskills.junit import JUnitSummary, parse_junit_files
from devskills.runner import AttemptOutcome, classify_attempt, decide_outcome
from tests._support import make_temp_dir, run_cli, write

PY = sys.executable


def junit_xml(passed=1, failed=0):
    cases = "".join(f'<testcase classname="t" name="ok{index}"/>' for index in range(passed))
    cases += "".join(f'<testcase classname="t" name="bad{index}"><failure message="boom"/></testcase>' for index in range(failed))
    return f'<?xml version="1.0"?><testsuite tests="{passed + failed}">{cases}</testsuite>'


def run_tests(repo, *args, env=None):
    completed = run_cli("run-tests", "--repo", str(repo), "--json", *args, env=env)
    try:
        return completed.returncode, json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"exit {completed.returncode}\n{completed.stdout}\n{completed.stderr}") from error


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class ClassificationTest(unittest.TestCase):
    def attempt(self, exit_code=0, junit=None, timed_out=False):
        return AttemptOutcome(1, exit_code, timed_out, 0.1, "o", "e", 0, 0, False, False, True, junit)

    def test_mapping(self):
        self.assertEqual(classify_attempt(self.attempt(0), False, ["npm", "test"])[2], "warn")
        self.assertEqual(classify_attempt(self.attempt(1), False, ["npm", "test"])[2], "fail")
        self.assertEqual(classify_attempt(self.attempt(5), False, ["python", "-m", "pytest"])[1], "no_tests")
        self.assertEqual(classify_attempt(self.attempt(0, JUnitSummary(files=["r.xml"])), True, ["x"])[1], "no_tests")
        self.assertEqual(classify_attempt(self.attempt(0, JUnitSummary()), True, ["x"])[1], "no_report")
        self.assertEqual(classify_attempt(self.attempt(0, JUnitSummary(tests=2, skipped=2, files=["r"])), True, ["x"])[1], "all_skipped")
        self.assertEqual(classify_attempt(self.attempt(1, JUnitSummary(tests=2, files=["r"])), True, ["x"])[1], "nonzero_exit")
        self.assertEqual(classify_attempt(self.attempt(0, JUnitSummary(tests=2, files=["r"])), True, ["x"])[2], "pass")
        self.assertEqual(classify_attempt(self.attempt(None, timed_out=True), True, ["x"])[2], "blocked")

    def test_pass_after_retry_is_flaky(self):
        attempts = [self.attempt(1), self.attempt(0, JUnitSummary(tests=1, files=["r"]))]
        self.assertEqual(decide_outcome(attempts, True, ["x"])[1:3], ("flaky", "blocked"))

    def test_partially_unparseable_reports_never_pass(self):
        report = JUnitSummary(tests=1, files=["ok.xml", "broken.xml"], parse_errors=["broken XML"])
        self.assertEqual(classify_attempt(self.attempt(0, report), True, ["x"])[2], "blocked")


class JUnitEvidenceTest(unittest.TestCase):
    def test_records_every_case_with_identity_and_outcome(self):
        root = make_temp_dir(self)
        report = write(root, "report.xml", '''<testsuite>
          <testcase file="tests/test_orders.py" classname="tests.test_orders.Orders" name="test_ok"/>
          <testcase classname="tests.test_orders.Orders" name="test_skip"><skipped/></testcase>
          <testcase classname="tests.test_orders.Orders" name="test_fail"><failure message="boom"/></testcase>
          <testcase classname="tests.test_orders.Orders" name="test_error"><error/></testcase>
        </testsuite>''')
        summary = parse_junit_files([report]).to_dict()
        self.assertEqual((summary["tests"], summary["passed"], summary["skipped"]), (4, 1, 1))
        self.assertEqual(summary["cases"][0], {"file": "tests/test_orders.py", "classname": "tests.test_orders.Orders",
                                               "name": "test_ok", "outcome": "passed"})
        self.assertEqual([case["outcome"] for case in summary["cases"]], ["passed", "skipped", "failure", "error"])

    def test_non_junit_xml_is_not_a_valid_report(self):
        root = make_temp_dir(self)
        report = write(root, "other.xml", '<document><testcase name="invented"/></document>')
        summary = parse_junit_files([report])
        self.assertEqual(summary.tests, 0)
        self.assertTrue(summary.parse_errors)


class RunTestsProcessTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_dir(self)

    def test_environment_allowlist_strips_secrets(self):
        write(self.repo, "probe.py", "import os\nprint('TOKEN=' + ('present' if 'MY_SECRET_TOKEN' in os.environ else 'absent'))\nprint('TZ=' + os.environ.get('TZ', ''))\n")
        code, record = run_tests(self.repo, "--", PY, "probe.py", env={"MY_SECRET_TOKEN": "s3cr3t"})
        self.assertEqual(code, 0)
        stdout = Path(record["details"]["attempts"][0]["stdout_log"]).read_text()
        self.assertIn("TOKEN=absent", stdout)
        self.assertIn("TZ=UTC", stdout)
        self.assertEqual(record["gate_result"], "warn", "exit 0 without a report is unverified")
        code, record = run_tests(self.repo, "--env", "MY_SECRET_TOKEN", "--", PY, "probe.py", env={"MY_SECRET_TOKEN": "s3cr3t"})
        self.assertIn("TOKEN=present", Path(record["details"]["attempts"][0]["stdout_log"]).read_text())
        self.assertEqual(record["details"]["env_passed_explicitly"], ["MY_SECRET_TOKEN"])

    def test_timeout_kills_the_whole_process_tree(self):
        write(self.repo, "slow.py", (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen(['sleep', '60'])\n"
            "open('grandchild.pid', 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"))
        started = time.monotonic()
        code, record = run_tests(self.repo, "--timeout", "2", "--", PY, "slow.py")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 4)
        self.assertEqual(record["execution_status"], "timed_out")
        grandchild = int((self.repo / "grandchild.pid").read_text())
        time.sleep(0.3)
        self.assertFalse(pid_alive(grandchild), "grandchild must be terminated with the group")

    def test_leftover_background_process_is_terminated(self):
        write(self.repo, "leak.py", (
            "import subprocess\n"
            "child = subprocess.Popen(['sleep', '60'])\n"
            "open('leak.pid', 'w').write(str(child.pid))\n"))
        _code, record = run_tests(self.repo, "--", PY, "leak.py")
        self.assertTrue(record["details"]["attempts"][0]["leftover_processes_terminated"])
        time.sleep(0.3)
        self.assertFalse(pid_alive(int((self.repo / "leak.pid").read_text())))

    def test_network_guard_blocks_outbound_but_allows_loopback(self):
        write(self.repo, "net.py", (
            "import socket, time\n"
            "server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1)\n"
            "client = socket.create_connection(server.getsockname(), timeout=2); print('LOOPBACK_OK')\n"
            "started = time.monotonic()\n"
            "try:\n"
            "    socket.create_connection(('203.0.113.1', 9), timeout=3)\n"
            "    print('NOT_BLOCKED')\n"
            "except OSError as error:\n"
            "    print('BLOCKED', type(error).__name__, round(time.monotonic() - started, 2))\n"))
        _code, record = run_tests(self.repo, "--", PY, "net.py")
        output = Path(record["details"]["attempts"][0]["stdout_log"]).read_text()
        self.assertIn("LOOPBACK_OK", output)
        self.assertIn("BLOCKED", output)
        self.assertNotIn("NOT_BLOCKED", output)

    @unittest.skipUnless(sys.platform == "darwin", "macOS sandbox-exec enforcement")
    def test_os_sandbox_blocks_even_without_python_guard(self):
        write(self.repo, "raw.py", (
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('203.0.113.1', 9), timeout=3); print('NOT_BLOCKED')\n"
            "except OSError as error:\n"
            "    print('BLOCKED', type(error).__name__)\n"))
        # -I ignores PYTHONPATH, so the sitecustomize guard is not loaded: only the OS sandbox can block.
        _code, record = run_tests(self.repo, "--", PY, "-I", "raw.py")
        output = Path(record["details"]["attempts"][0]["stdout_log"]).read_text()
        self.assertIn("BLOCKED PermissionError", output)
        self.assertTrue(record["details"]["network_enforcement"].startswith("os_sandbox"))

    def test_junit_results_map_to_gates(self):
        write(self.repo, "report.py", "import sys\nopen('junit.xml', 'w').write(sys.argv[1])\nsys.exit(int(sys.argv[2]))\n")
        code, record = run_tests(self.repo, "--junit", "junit.xml", "--", PY, "report.py", junit_xml(2, 1), "1")
        self.assertEqual((code, record["gate_result"], record["domain_result"]), (3, "fail", "failed"))
        self.assertEqual(record["details"]["attempts"][0]["junit"]["failed_cases"][0]["message"], "boom")
        code, record = run_tests(self.repo, "--junit", "junit.xml", "--", PY, "report.py", junit_xml(3, 0), "0")
        self.assertEqual((code, record["gate_result"]), (0, "pass"))
        code, record = run_tests(self.repo, "--junit", "junit.xml", "--", PY, "report.py", junit_xml(0, 0), "0")
        self.assertEqual(record["domain_result"], "no_tests")

    def test_good_and_broken_reports_block_the_run(self):
        write(self.repo, "report.py", "from pathlib import Path\n"
              "Path('good.xml').write_text('<testsuite><testcase name=\"ok\"/></testsuite>')\n"
              "Path('broken.xml').write_text('<testsuite><testcase')\n")
        code, record = run_tests(self.repo, "--junit", "*.xml", "--", PY, "report.py")
        self.assertEqual((code, record["gate_result"]), (4, "blocked"))
        self.assertTrue(record["details"]["attempts"][0]["junit"]["parse_errors"])

    def test_stale_report_from_earlier_run_is_ignored(self):
        report = write(self.repo, "old.xml", junit_xml(5, 0))
        old = time.time() - 3600
        os.utime(report, (old, old))
        write(self.repo, "noop.py", "print('did nothing')\n")
        code, record = run_tests(self.repo, "--junit", "old.xml", "--", PY, "noop.py")
        self.assertEqual((code, record["domain_result"]), (4, "no_report"))
        self.assertTrue(record["details"]["attempts"][0]["stale_reports_ignored"])

    def test_preflight_blocks_before_anything_runs(self):
        write(self.repo, ".env.test", "DATABASE_URL=postgres://u:p@orders.prod.example.com/app\n")  # devskills:allow-secret fake fixture credential for preflight tests
        write(self.repo, "touch.py", "open('ran.marker', 'w').write('x')\n")
        code, record = run_tests(self.repo, "--", PY, "touch.py")
        self.assertEqual((code, record["execution_status"]), (4, "not_run"))
        self.assertFalse((self.repo / "ran.marker").exists())

    def test_output_is_capped(self):
        write(self.repo, ".devskills.toml", "[testing]\nmax_output_bytes = 10000\n")
        write(self.repo, "loud.py", "for index in range(20000):\n    print('line', index, 'x' * 20)\n")
        _code, record = run_tests(self.repo, "--", PY, "loud.py")
        attempt = record["details"]["attempts"][0]
        self.assertTrue(attempt["truncated"])
        self.assertGreater(attempt["stdout_bytes"], 100000)
        self.assertLess(Path(attempt["stdout_log"]).stat().st_size, 12000)

    def test_retry_that_passes_is_reported_flaky(self):
        write(self.repo, "flaky.py", (
            "import os, sys\n"
            "first = not os.path.exists('attempted')\n"
            "open('attempted', 'w').write('1')\n"
            "sys.exit(1 if first else 0)\n"))
        code, record = run_tests(self.repo, "--retries", "1", "--", PY, "flaky.py")
        self.assertEqual((code, record["domain_result"]), (4, "flaky"))
        self.assertEqual(len(record["details"]["attempts"]), 2)

    def test_missing_executable_is_blocked(self):
        code, record = run_tests(self.repo, "--", "definitely-not-a-real-tool-xyz")
        self.assertEqual((code, record["domain_result"]), (4, "executable_not_found"))

    def test_command_is_required(self):
        completed = run_cli("run-tests", "--repo", str(self.repo))
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
