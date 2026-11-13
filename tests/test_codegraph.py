"""CodeGraph integration flag (auto/on/off) with a fake `codegraph` CLI, so tests never need the real tool."""

import json
import os
import sys
import unittest
from pathlib import Path

from devskills.codegraph import resolve_mode
from devskills.models import UsageError
from tests._support import commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write

FAKE_CLI = """#!{python}
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("1.2.0-fake")
    sys.exit(0)
with open(os.environ["FAKE_CODEGRAPH_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if args[0] == "status":
    print(json.dumps({{"initialized": True, "lastIndexed": "2026-10-28T00:00:00Z", "fileCount": 3, "nodeCount": 10,
                      "edgeCount": 12, "pendingChanges": {{"added": 0, "modified": 1, "removed": 0}},
                      "index": {{"reindexRecommended": False}}, "worktreeMismatch": None}}))
elif args[0] == "explore":
    print("\\x1b[1m**Exploration: order**\\x1b[0m\\n\\n- `OrderService` (app/orders/service.py:1) — 1 caller")
elif args[0] == "affected":
    print(json.dumps({{"changedFiles": args[4:], "affectedTests": ["tests/test_orders.py"], "totalDependentsTraversed": 2}}))
else:
    sys.exit(2)
"""


class ResolveModeTest(unittest.TestCase):
    def test_precedence_and_validation(self):
        profile = {"integrations": {"codegraph": "off"}}
        self.assertEqual(resolve_mode(None, {}), "auto")
        self.assertEqual(resolve_mode(None, profile), "off")
        self.assertEqual(resolve_mode("on", profile), "on", "the CLI flag wins")
        os.environ["DEVSKILLS_CODEGRAPH"] = "on"
        try:
            self.assertEqual(resolve_mode(None, profile), "on", "the environment beats the profile")
        finally:
            del os.environ["DEVSKILLS_CODEGRAPH"]
        with self.assertRaises(UsageError):
            resolve_mode("sometimes", {})


class InspectWithCodeGraphTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_dir(self)
        init_git_repo(self.repo)
        write(self.repo, "app/orders/service.py", "class OrderService:\n    pass\n")
        commit_all(self.repo)
        write(self.repo, "app/orders/service.py", "class OrderService:\n    total_minor = 0\n")
        bin_dir = make_temp_dir(self)
        fake = bin_dir / "codegraph"
        fake.write_text(FAKE_CLI.format(python=sys.executable))
        fake.chmod(0o755)
        self.log = bin_dir / "calls.log"
        self.env = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", "FAKE_CODEGRAPH_LOG": str(self.log)}

    def inspect(self, *extra, env=None):
        code, record = run_cli_json("inspect", "--repo", str(self.repo), "--feature", "order", *extra, env=env or self.env)
        context = json.loads(Path(record["details"]["context_map"]).read_text())
        return code, record, context

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_auto_without_index_does_not_query_or_index(self):
        code, _record, context = self.inspect()
        self.assertEqual(code, 0)
        self.assertFalse(context["code_graph"]["available"])
        self.assertIn("not indexed", context["code_graph"]["reason"])
        self.assertEqual(self.calls(), [], "never runs `codegraph init` or queries without an index")
        self.assertFalse((self.repo / ".codegraph").exists())

    def test_auto_with_index_adds_exploration_and_affected_tests(self):
        write(self.repo, ".codegraph/codegraph.db", b"")
        code, record, context = self.inspect()
        self.assertEqual(code, 0, record)
        graph = context["code_graph"]
        self.assertTrue(graph["available"])
        self.assertEqual(graph["version"], "1.2.0-fake")
        self.assertEqual(graph["index"]["pending_changes"], 1)
        self.assertEqual(graph["affected_tests"], ["tests/test_orders.py"])
        exploration = Path(graph["explore_file"]).read_text()
        self.assertIn("OrderService", exploration)
        self.assertNotIn("\x1b[", exploration, "ANSI colours are stripped")
        commands = [line.split()[0] for line in self.calls()]
        self.assertEqual(sorted(set(commands)), ["affected", "explore", "status"])
        self.assertTrue(any(line.endswith("app/orders/service.py") for line in self.calls() if line.startswith("affected")))
        markdown = Path(record["details"]["markdown"]).read_text()
        self.assertIn("## Code graph (CodeGraph)", markdown)
        self.assertIn("tests/test_orders.py", markdown)

    def test_off_never_calls_codegraph(self):
        write(self.repo, ".codegraph/codegraph.db", b"")
        _code, _record, context = self.inspect("--codegraph", "off")
        self.assertEqual(context["code_graph"]["mode"], "off")
        self.assertEqual(self.calls(), [])
        write(self.repo, ".devskills.toml", "[integrations]\ncodegraph = 'off'\n")
        _code, _record, context = self.inspect()
        self.assertEqual(context["code_graph"]["mode"], "off", "profile switch")
        _code, _record, context = self.inspect(env=self.env | {"DEVSKILLS_CODEGRAPH": "auto"})
        self.assertTrue(context["code_graph"]["available"], "environment overrides the profile")

    def test_on_without_cli_warns(self):
        code, record, context = self.inspect("--codegraph", "on", env={"PATH": f"/usr/bin{os.pathsep}/bin"})
        self.assertEqual((code, record["gate_result"]), (0, "warn"))
        self.assertIn("not installed", context["code_graph"]["reason"])

    def test_invalid_mode_is_a_usage_error(self):
        write(self.repo, ".devskills.toml", "[integrations]\ncodegraph = 'maybe'\n")
        self.assertEqual(run_cli("inspect", "--repo", str(self.repo), env=self.env).returncode, 2)


if __name__ == "__main__":
    unittest.main()
