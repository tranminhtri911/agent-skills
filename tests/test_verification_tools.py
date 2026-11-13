"""native-checks, trace, api-diff, project conventions and the roster rules that expect them."""

import json
import sys
import unittest

from devskills.api_contract import diff_specs
from devskills.conventions import detect_conventions, reference_modules
from devskills.inventory import feature_pattern
from devskills.native import plan_checks, touched_project_dirs
from devskills.runs import build_default_roster, tag_changed_paths
from tests._support import commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write

PY = sys.executable


def spec(paths: dict, schemas: dict | None = None) -> dict:
    return {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths,
            "components": {"schemas": schemas or {}}}


def order_spec(**overrides) -> dict:
    """POST /orders with a request body and a 201 response; overrides patch the schemas."""
    request = {"type": "object", "required": ["sku"], "properties": {
        "sku": {"type": "string", "maxLength": 40}, "note": {"type": "string", "nullable": True},
        "channel": {"type": "string", "enum": ["web", "app"]}}}
    response = {"type": "object", "required": ["id", "total"], "properties": {
        "id": {"type": "integer"}, "total": {"type": "integer"}, "status": {"type": "string", "enum": ["new", "paid"]}}}
    request.update(overrides.get("request", {}))
    response.update(overrides.get("response", {}))
    operation = {"parameters": overrides.get("parameters", [{"name": "page", "in": "query", "schema": {"type": "integer"}}]),
                 "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderIn"}}}},
                 "responses": {"201": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderOut"}}}}}}
    return spec({"/orders": {"post": operation}}, {"OrderIn": request, "OrderOut": response})


class ApiDiffTest(unittest.TestCase):
    def rules(self, before, after):
        return {(finding.rule_id, finding.message.split(":")[0]) for finding in diff_specs(before, after)}

    def test_identical_specs_have_no_findings(self):
        self.assertEqual(diff_specs(order_spec(), order_spec()), [])

    def test_request_side_breaking_changes(self):
        tightened = order_spec(request={"required": ["sku", "channel"], "properties": {
            "sku": {"type": "string", "maxLength": 20}, "note": {"type": "string"},
            "channel": {"type": "string", "enum": ["web"]}}})
        rule_ids = {rule for rule, _ in self.rules(order_spec(), tightened)}
        self.assertTrue({"API-BREAK-REQUIRED", "API-BREAK-CONSTRAINT", "API-BREAK-NULLABLE", "API-BREAK-ENUM"} <= rule_ids, rule_ids)

    def test_response_side_breaking_changes_and_enum_warning(self):
        loosened = order_spec(response={"required": ["id"], "properties": {
            "id": {"type": "string"}, "total": {"type": "integer", "nullable": True},
            "status": {"type": "string", "enum": ["new", "paid", "refunded"]}}})
        findings = diff_specs(order_spec(), loosened)
        by_rule = {finding.rule_id: finding for finding in findings}
        self.assertIn("API-BREAK-TYPE", by_rule)
        self.assertIn("API-BREAK-REQUIRED", by_rule)
        self.assertIn("API-BREAK-NULLABLE", by_rule)
        self.assertEqual(by_rule["API-WARN-ENUM"].severity, "low", "a new response enum value is a warning, not a break")

    def test_additive_changes_are_safe(self):
        added = order_spec(request={"properties": {
            "sku": {"type": "string", "maxLength": 80}, "note": {"type": "string", "nullable": True},
            "channel": {"type": "string", "enum": ["web", "app", "pos"]}, "coupon": {"type": "string"}}},
            response={"properties": {"id": {"type": "integer"}, "total": {"type": "integer"},
                                     "status": {"type": "string", "enum": ["new", "paid"]}, "eta": {"type": "string"}}})
        self.assertEqual([finding.rule_id for finding in diff_specs(order_spec(), added)], [])

    def test_removed_operation_and_new_required_parameter(self):
        with_param = order_spec(parameters=[{"name": "page", "in": "query", "schema": {"type": "integer"}},
                                            {"name": "X-Tenant", "in": "header", "required": True, "schema": {"type": "string"}}])
        self.assertIn("API-BREAK-REQUIRED", {rule for rule, _ in self.rules(order_spec(), with_param)})
        self.assertIn("API-BREAK-PATH-REMOVED", {rule for rule, _ in self.rules(order_spec(), spec({}))})

    def test_recursive_schema_terminates(self):
        tree = {"type": "object", "properties": {"children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}}}
        document = spec({"/nodes": {"get": {"responses": {"200": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Node"}}}}}}}}, {"Node": tree})
        self.assertEqual(diff_specs(document, document), [])

    def test_cli_against_git_base_records_failure(self):
        root = make_temp_dir(self)
        init_git_repo(root)
        write(root, "docs/openapi.json", json.dumps(order_spec()))
        commit_all(root)
        write(root, "docs/openapi.json", json.dumps(spec({})))
        code, payload = run_cli_json("api-diff", "--repo", str(root), "--spec", "docs/openapi.json", "--base-ref", "HEAD")
        self.assertEqual(code, 3, payload)
        self.assertEqual(payload["check_id"], "api.contract_diff")
        missing = run_cli("api-diff", "--repo", str(root), "--spec", "docs/openapi.json", "--base-ref", "HEAD",
                          "--base-file", "x.json")
        self.assertEqual(missing.returncode, 2, "exactly one base source is required")


class NativeChecksTest(unittest.TestCase):
    def test_plans_node_python_and_blocks_unsafe_scripts(self):
        root = make_temp_dir(self)
        write(root, "frontend/package.json", json.dumps({"scripts": {
            "lint": "eslint src", "build": "vite build && firebase deploy", "typecheck": "tsc --noEmit"}}))
        write(root, "frontend/package-lock.json", "{}")
        write(root, "frontend/node_modules/.bin/eslint", "")
        write(root, "backend/manage.py", "")
        write(root, "backend/pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        checks = {check.check_id: check for check in plan_checks(root, {"typecheck", "lint", "build", "framework", "migrations"})}
        self.assertEqual(checks["native.lint.frontend"].source, "package.json scripts.lint", "scripts win over raw binaries")
        self.assertIn("side effects", checks["native.build.frontend"].blocked_reason)
        self.assertEqual(checks["native.framework.backend"].argv[-1], "check")
        self.assertEqual(checks["native.migrations.backend"].argv[-3:], ["makemigrations", "--check", "--dry-run"])
        self.assertIn("native.lint.backend", checks)
        self.assertEqual(touched_project_dirs(root, ["backend/api/views.py", "README.md"]), {"backend"})

    def test_classic_dotnet_is_blocked_with_reason(self):
        root = make_temp_dir(self)
        write(root, "App.sln", "")
        write(root, "Web/Web.csproj", '<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003"></Project>')
        checks = plan_checks(root, {"build"})
        self.assertEqual([check.check_id for check in checks], ["native.build", "native.build.web"])
        for check in checks:
            self.assertIn("classic .NET Framework", check.blocked_reason, "solution and project are both MSBuild-only")

    def test_execute_records_pass_for_exit_zero_tool(self):
        root = make_temp_dir(self)
        init_git_repo(root)
        write(root, "Makefile", f"lint:\n\t{PY} -c \"print('lint ok')\"\n")
        commit_all(root)
        started = run_cli_json("run", "start", "--repo", str(root), "--risk", "R1")[1]
        code, payload = run_cli_json("native-checks", "--repo", str(root), "--all-projects", "--execute",
                                     "--kinds", "lint", "--run", started["run_id"])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["checks"][0]["check_id"], "native.lint")
        self.assertEqual(payload["checks"][0]["gate_result"], "pass", "exit 0 is evidence for a linter")
        self.assertTrue((root / ".devskills" / "runs" / started["run_id"] / "checks" / "native.lint.json").is_file())


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.root = make_temp_dir(self)
        init_git_repo(self.root)
        write(self.root, "tests/test_orders.py", "def test_retry_creates_one_order():\n    pass\n")
        commit_all(self.root)
        self.run_id = run_cli_json("run", "start", "--repo", str(self.root), "--risk", "R1")[1]["run_id"]
        self.checks = self.root / ".devskills" / "runs" / self.run_id / "checks"
        self.unit = {"check_id": "tests.unit", "execution_status": "completed", "gate_result": "pass", "details": {
            "attempts": [{"exit_code": 0, "timed_out": False, "junit": {"tests": 1, "files": ["report.xml"],
                "parse_errors": [], "cases": [{"file": "", "classname": "tests.test_orders",
                    "name": "test_retry_creates_one_order", "outcome": "passed"}], "failed_cases": []}}]}}
        self.save_unit()
        write(self.checks, "tests.integration.json", json.dumps({"check_id": "tests.integration", "gate_result": "fail"}))

    def save_unit(self):
        write(self.checks, "tests.unit.json", json.dumps(self.unit))

    def trace_test(self, reference):
        return self.trace([{"id": "AC-1", "text": "behavior", "evidence": [{"test": reference, "check": "tests.unit"}]}])

    def trace(self, criteria):
        path = write(self.root, "acceptance.json", json.dumps({"criteria": criteria}))
        return run_cli_json("trace", "--repo", str(self.root), "--run", self.run_id, "--file", str(path))

    def test_statuses(self):
        code, payload = self.trace([
            {"id": "AC-1", "text": "retry creates one order", "tags": ["idempotency"],
             "evidence": [{"test": "tests/test_orders.py::test_retry_creates_one_order", "check": "tests.unit"}]},
            {"id": "AC-2", "text": "manual only", "evidence": [{"review": "checked with PO"}]},
            {"id": "AC-3", "text": "missing test", "evidence": [{"test": "tests/test_orders.py::test_nope", "check": "tests.unit"}]},
            {"id": "AC-4", "text": "failing check", "evidence": [{"check": "tests.integration"}]},
        ])
        statuses = {row["id"]: row["status"] for row in payload["details"]["criteria"]}
        self.assertEqual(statuses, {"AC-1": "verified", "AC-2": "weak", "AC-3": "unverified", "AC-4": "failed"})
        self.assertEqual((payload["gate_result"], code), ("fail", 3))
        matrix = self.root / ".devskills" / "runs" / self.run_id / "artifacts" / "traceability.md"
        self.assertIn("| AC-1 |", matrix.read_text())

    def test_failed_junit_case_marks_criterion_failed(self):
        write(self.root, "tests/test_orders.py", "def test_retry_creates_one_order():\n    pass\ndef test_cancel_refunds():\n    pass\n")
        self.unit["gate_result"] = "fail"
        self.unit["details"]["attempts"][0]["junit"]["cases"].append(
            {"file": "", "classname": "tests.test_orders", "name": "test_cancel_refunds", "outcome": "failure"})
        self.save_unit()
        _code, payload = self.trace([{"id": "AC-9", "text": "cancel refunds",
                                      "evidence": [{"test": "tests/test_orders.py::test_cancel_refunds", "check": "tests.unit"}]}])
        self.assertEqual(payload["details"]["criteria"][0]["status"], "failed")

    def test_all_verified_passes_and_duplicate_ids_are_rejected(self):
        code, payload = self.trace([{"id": "AC-1", "text": "ok", "evidence": [
            {"test": "tests/test_orders.py::test_retry_creates_one_order", "check": "tests.unit"}]}])
        self.assertEqual((code, payload["gate_result"]), (0, "pass"))
        duplicate = write(self.root, "dup.json", json.dumps({"criteria": [{"id": "A"}, {"id": "A"}]}))
        completed = run_cli("trace", "--repo", str(self.root), "--run", self.run_id, "--file", str(duplicate))
        self.assertEqual(completed.returncode, 2)

    def test_preservation_cannot_be_proven_by_current_pass_alone(self):
        for tag in ("refactor", "preservation"):
            with self.subTest(tag=tag):
                code, payload = self.trace([{"id": "KEEP-1", "text": "existing behavior unchanged", "tags": [tag],
                    "evidence": [{"test": "tests/test_orders.py::test_retry_creates_one_order", "check": "tests.unit"}]}])
                self.assertEqual((code, payload["details"]["criteria"][0]["status"]), (4, "unverified"))

    def test_test_not_in_report_is_unverified(self):
        write(self.root, "tests/test_orders.py", "def test_retry_creates_one_order():\n    pass\ndef test_not_run():\n    assert False\n")
        code, payload = self.trace_test("tests/test_orders.py::test_not_run")
        self.assertEqual((code, payload["details"]["criteria"][0]["status"]), (4, "unverified"))

    def test_skipped_case_is_unverified_even_when_other_tests_pass(self):
        self.unit["details"]["attempts"][0]["junit"]["cases"][0]["outcome"] = "skipped"
        self.save_unit()
        code, payload = self.trace_test("tests/test_orders.py::test_retry_creates_one_order")
        self.assertEqual((code, payload["details"]["criteria"][0]["status"]), (4, "unverified"))

    def test_same_name_in_another_module_is_unverified(self):
        self.unit["details"]["attempts"][0]["junit"]["cases"][0]["classname"] = "tests.test_other"
        self.save_unit()
        code, _ = self.trace_test("tests/test_orders.py::test_retry_creates_one_order")
        self.assertEqual(code, 4)

    def test_same_method_in_another_class_is_unverified(self):
        write(self.root, "tests/test_orders.py", "class Wanted:\n    def test_retry_creates_one_order(self):\n        pass\n")
        self.unit["details"]["attempts"][0]["junit"]["cases"][0]["classname"] = "tests.test_orders.Other"
        self.save_unit()
        code, _ = self.trace_test("tests/test_orders.py::Wanted::test_retry_creates_one_order")
        self.assertEqual(code, 4)

    def test_parameter_ids_must_match_exactly(self):
        self.unit["details"]["attempts"][0]["junit"]["cases"][0]["name"] += "[paid]"
        self.save_unit()
        for selector, expected in (("", 4), ("[declined]", 4), ("[paid]", 0)):
            with self.subTest(selector=selector):
                code, _ = self.trace_test("tests/test_orders.py::test_retry_creates_one_order" + selector)
                self.assertEqual(code, expected)

    def test_file_attribute_supports_reporters_without_module_names(self):
        case = self.unit["details"]["attempts"][0]["junit"]["cases"][0]
        case.update(file="tests/test_orders.py", classname="")
        self.save_unit()
        self.assertEqual(self.trace_test("tests/test_orders.py::test_retry_creates_one_order")[0], 0)
        case["file"] = "tests/test_other.py"
        self.save_unit()
        self.assertEqual(self.trace_test("tests/test_orders.py::test_retry_creates_one_order")[0], 4)

    def test_relative_file_attribute_uses_recorded_command_directory(self):
        write(self.root, "backend/tests/test_orders.py", "def test_retry_creates_one_order():\n    pass\n")
        self.unit["details"]["cwd"] = "backend"
        case = self.unit["details"]["attempts"][0]["junit"]["cases"][0]
        case.update(file="tests/test_orders.py", classname="")
        self.save_unit()
        self.assertEqual(self.trace_test("backend/tests/test_orders.py::test_retry_creates_one_order")[0], 0)
        self.assertEqual(self.trace_test("tests/test_orders.py::test_retry_creates_one_order")[0], 4)

    def test_file_match_cannot_replace_a_missing_class_selector(self):
        case = self.unit["details"]["attempts"][0]["junit"]["cases"][0]
        case.update(file="tests/test_orders.py", classname="tests.test_orders.Other")
        self.save_unit()
        self.assertEqual(self.trace_test("tests/test_orders.py::test_retry_creates_one_order")[0], 4)

    def test_file_match_cannot_replace_the_qualified_class(self):
        write(self.root, "tests/test_orders.py", "class Wanted:\n    def test_retry_creates_one_order(self):\n        pass\n")
        case = self.unit["details"]["attempts"][0]["junit"]["cases"][0]
        case.update(file="tests/test_orders.py", classname="tests.test_orders.Other.Wanted")
        self.save_unit()
        reference = "tests/test_orders.py::Wanted::test_retry_creates_one_order"
        self.assertEqual(self.trace_test(reference)[0], 4)
        for classname in ("Wanted", "tests.test_orders.Wanted"):
            case["classname"] = classname
            self.save_unit()
            self.assertEqual(self.trace_test(reference)[0], 0)

    def test_duplicate_case_records_are_not_unambiguous_evidence(self):
        cases = self.unit["details"]["attempts"][0]["junit"]["cases"]
        cases.append(dict(cases[0]))
        self.save_unit()
        self.assertEqual(self.trace_test("tests/test_orders.py::test_retry_creates_one_order")[0], 4)

    def test_incomplete_or_unexecuted_evidence_is_unverified(self):
        for defect in ("legacy", "parse_error", "not_run", "nonzero", "timeout", "file_only"):
            with self.subTest(defect=defect):
                record = json.loads(json.dumps(self.unit))
                attempt = self.unit["details"]["attempts"][0]
                reference = "tests/test_orders.py::test_retry_creates_one_order"
                if defect == "legacy":
                    attempt["junit"].pop("cases")
                elif defect == "parse_error":
                    attempt["junit"]["parse_errors"] = ["broken report"]
                elif defect == "not_run":
                    self.unit["execution_status"] = "not_run"
                elif defect == "nonzero":
                    attempt["exit_code"] = 1
                elif defect == "timeout":
                    attempt["timed_out"] = True
                else:
                    reference = "tests/test_orders.py"
                self.save_unit()
                code, _ = self.trace_test(reference)
                self.assertEqual(code, 4)
                self.unit = record

    def test_real_runner_does_not_verify_an_unexecuted_test(self):
        write(self.root, "tests/test_orders.py", '''import unittest
from pathlib import Path
class Orders(unittest.TestCase):
    def test_ran(self):
        self.assertEqual(2 + 2, 4)
    def test_not_run(self):
        Path("unexpected-test-ran").touch()
        self.fail("must fail if executed")
''')
        write(self.root, "run_one.py", '''import importlib.util
import sys
import unittest
from xml.etree.ElementTree import Element, SubElement, ElementTree
spec = importlib.util.spec_from_file_location("tests.test_orders", "tests/test_orders.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = unittest.TextTestRunner().run(unittest.TestSuite([module.Orders("test_ran")]))
suite = Element("testsuite")
case = SubElement(suite, "testcase", classname="tests.test_orders.Orders", name="test_ran")
if not result.wasSuccessful():
    SubElement(case, "failure")
ElementTree(suite).write("report.xml", encoding="unicode")
sys.exit(0 if result.wasSuccessful() else 1)
''')
        completed = run_cli("run-tests", "--repo", str(self.root), "--run", self.run_id, "--json",
                            "--junit", "report.xml", "--", PY, "run_one.py")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for name, expected in (("test_ran", 0), ("test_not_run", 4)):
            with self.subTest(name=name):
                code, _ = self.trace_test(f"tests/test_orders.py::Orders::{name}")
                self.assertEqual(code, expected)
        self.assertFalse((self.root / "unexpected-test-ran").exists())


class RosterAndConventionsTest(unittest.TestCase):
    def test_roster_expects_native_trace_and_contract_checks(self):
        tags = tag_changed_paths(["backend/api/models.py", "docs/openapi.yaml"])
        self.assertIn("api_spec", tags)
        native = [("native.lint.backend", "lint"), ("native.typecheck.backend", "typecheck"),
                  ("native.build.backend", "build"), ("native.migrations.backend", "migrations")]
        r1 = {entry["check_id"]: entry["required"] for entry in build_default_roster("R1", tags | {"code"}, native)}
        self.assertTrue(r1["trace.acceptance"] and r1["api.contract_diff"] and r1["native.migrations.backend"])
        self.assertNotIn("native.build.backend", r1, "builds are expected from R2")
        r2 = {entry["check_id"] for entry in build_default_roster("R2", tags | {"code"}, native)}
        self.assertIn("native.build.backend", r2)
        r0 = {entry["check_id"] for entry in build_default_roster("R0", {"docs"}, native)}
        self.assertNotIn("trace.acceptance", r0)

    def test_conventions_find_project_bases_hooks_and_reference_modules(self):
        texts = {
            "core/base.py": "class BaseService:\n    pass\n",
            "orders/service.py": "@transaction.atomic\nclass OrderService(BaseService):\n    pass\n",
            "invoices/service.py": "@transaction.atomic\nclass InvoiceService(BaseService):\n    pass\n",
            "api/migrations/0001.py": "class Migration(migrations.Migration):\n    pass\n",
            "api/migrations/0002.py": "class Migration(migrations.Migration):\n    pass\n",
            "web/hooks/useApi.ts": "export function useApi() {}\n",
            "web/pages/Orders.tsx": "const data = useApi();\n",
            "app/Http/Controllers/OrderController.php": "class OrderController extends Controller {}\n",
            "app/Http/Controllers/BankInfoController.php": "class BankInfoController extends Controller {}\n",
        }
        conventions = detect_conventions(texts, ["orders/service.py", "app/Http/Controllers/OrderController.php"])
        bases = {item["name"]: item for item in conventions["base_types"]}
        self.assertEqual(bases["BaseService"]["defined_in"], "core/base.py:1")
        self.assertIsNone(bases["migrations.Migration"]["defined_in"], "framework bases are not project-owned")
        self.assertEqual(conventions["custom_hooks"][0]["name"], "useApi")
        self.assertEqual(conventions["frequent_decorators"][0]["name"], "transaction.atomic")
        references = {item["path"] for item in conventions["reference_modules"]}
        self.assertIn("app/Http/Controllers/BankInfoController.php", references)
        folders = reference_modules(["apps/orders/a.py", "apps/orders/b.py", "apps/invoices/a.py", "apps/invoices/b.py"],
                                    ["apps/orders/a.py"], feature_pattern(["order"]))
        self.assertIn("apps/invoices", {item["path"] for item in folders})



class HelpTest(unittest.TestCase):
    def test_every_option_has_help_and_help_command_works(self):
        import argparse

        from devskills.cli import build_parser

        missing = []

        def walk(parser, prefix):
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        walk(sub, f"{prefix} {name}")
                elif action.help is None:
                    missing.append(f"{prefix} {(action.option_strings or [action.dest])[0]}")

        walk(build_parser(), "ds.py")
        self.assertEqual(missing, [])
        overview = run_cli("help")
        self.assertEqual(overview.returncode, 0)
        self.assertIn("typical flow for a change", overview.stdout)
        detail = run_cli("help", "footprint")
        self.assertEqual(detail.returncode, 0)
        self.assertIn("--allow-protected", detail.stdout)


if __name__ == "__main__":
    unittest.main()
