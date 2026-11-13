"""API-011 static coverage, schema/curl mismatches and real offline evidence capture."""

import copy
import importlib.util
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

from devskills.api_contract import SpecUnavailable
from devskills.api_examples import load_contract, load_json
from devskills.api_sample_curl import parse_curl
from devskills.api_sample_schema import SampleSchemas
from devskills.models import UsageError
from devskills.runs import build_default_roster
from tests._support import REPO_ROOT, commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write

ASSETS = REPO_ROOT / "skills/design-api/assets"


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional contracts extra")
class ApiExamplesTest(unittest.TestCase):
    def setUp(self):
        self.root = make_temp_dir(self)
        init_git_repo(self.root)
        write(self.root, ".gitignore", ".devskills/\n__pycache__/\n")
        write(self.root, "docs/api.md", "# Widgets\nSynthetic endpoint documentation for this test fixture.\n")
        write(self.root, "app.py", "# Synthetic API source fixture; never imported for discovery.\n")
        self.spec = json.loads((ASSETS / "openapi-example.json").read_text())
        self.manifest = json.loads((ASSETS / "api-examples.json").read_text())
        self.endpoint = self.manifest["endpoints"][0]
        self.endpoint.update(documentation="docs/api.md#widgets", sources=["app.py"])
        self.operation = self.spec["paths"]["/widgets"]["post"]
        self.run_id = None

    def save(self):
        write(self.root, "docs/openapi.json", json.dumps(self.spec))
        write(self.root, "docs/api-examples.json", json.dumps(self.manifest))

    def check(self):
        self.save()
        args = ["api-examples", "--repo", str(self.root), "--spec", "docs/openapi.json", "--file", "docs/api-examples.json"]
        if self.run_id:
            args += ["--run", self.run_id]
        completed = run_cli(*args, "--json")
        if completed.returncode == 2:
            return 2, {"error": completed.stderr}
        return completed.returncode, json.loads(completed.stdout)

    def codes(self):
        code, payload = self.check()
        self.assertEqual(code, 3, payload)
        return {finding["rule_id"] for finding in payload["findings"]}

    def recurl(self, case):
        request = case["request"]
        url = self.manifest["base_url"] + self.endpoint["path"]
        for key, value in request["path"].items():
            url = url.replace("{" + key + "}", str(value))
        import shlex
        argv = ["curl", "--request", self.endpoint["method"], url]
        for key, value in request["headers"].items():
            argv += ["--header", key + ": " + value]
        if "body" in request:
            argv += ["--data-raw", json.dumps(request["body"])]
        case["curl"] = shlex.join(argv)

    def bodyless(self, method="DELETE", status=204):
        self.operation.pop("requestBody")
        self.operation["responses"] = {str(status): {"description": "No response body"}}
        self.spec["paths"]["/widgets"] = {method.lower(): self.operation}
        self.endpoint["method"] = method
        self.endpoint["inputs"] = {}
        self.endpoint["cases"] = [self.endpoint["cases"][0]]
        self.endpoint["applicability"]["validation"] = {"reason": "This bodyless fixture declares no validation failure."}
        case = self.endpoint["cases"][0]
        case["request"] = {"path": {}, "query": {}, "headers": {}}
        case["response"] = {"status": status, "headers": {}}
        self.recurl(case)

    def test_complete_illustrative_samples_pass_without_execution(self):
        code, payload = self.check()
        self.assertEqual((code, payload["gate_result"]), (0, "pass"), payload)
        self.assertEqual(payload["details"]["network_requests"], 0)
        self.assertEqual(payload["details"]["endpoints"][0]["linked_local_evidence"], 0)

    def test_missing_unknown_duplicate_endpoints_and_cases_fail(self):
        original_spec, original_manifest = copy.deepcopy(self.spec), copy.deepcopy(self.manifest)
        for defect in ("missing", "unknown", "duplicate", "case"):
            with self.subTest(defect=defect):
                self.spec, self.manifest = copy.deepcopy(original_spec), copy.deepcopy(original_manifest)
                endpoint = self.manifest["endpoints"][0]
                if defect == "missing":
                    self.spec["paths"]["/undocumented"] = {"get": self.spec["paths"]["/widgets"]["post"]}
                elif defect == "unknown":
                    endpoint["method"] = "GET"
                elif defect == "duplicate":
                    self.manifest["endpoints"].append(copy.deepcopy(endpoint))
                else:
                    endpoint["cases"].append(copy.deepcopy(endpoint["cases"][0]))
                self.codes()

    def test_missing_required_documentation_sections_fail(self):
        original = copy.deepcopy(self.manifest)
        for field in ("purpose", "permissions", "effects", "inputs", "applicability", "cases", "documentation", "sources"):
            with self.subTest(field=field):
                self.manifest = copy.deepcopy(original)
                self.manifest["endpoints"][0].pop(field)
                self.assertIn("API-EXAMPLES-FORMAT", self.codes())

    def test_blank_reasons_missing_response_and_false_na_fail(self):
        self.endpoint["applicability"]["validation"] = {"reason": ""}
        self.assertIn("API-EXAMPLES-FORMAT", self.codes())
        self.endpoint["applicability"]["validation"] = {"reason": "Not tested yet."}
        self.assertIn("API-EXAMPLES-APPLICABILITY", self.codes())
        self.endpoint["applicability"]["validation"] = {"cases": ["invalid-name"]}
        self.endpoint["cases"].pop()
        self.assertIn("API-EXAMPLES-COVERAGE", self.codes())

    def test_missing_nested_input_and_invalid_field_example_fail(self):
        self.endpoint["inputs"].pop("body:application/json:/note")
        self.assertIn("API-EXAMPLES-INPUTS", self.codes())
        self.endpoint["inputs"]["body:application/json:/name"]["example"] = None
        self.assertIn("API-EXAMPLES-INPUT-EXAMPLE", self.codes())

    def test_every_request_media_type_needs_a_successful_invocation(self):
        content = self.operation["requestBody"]["content"]
        content["application/vnd.example+json"] = copy.deepcopy(content["application/json"])
        for key, value in list(self.endpoint["inputs"].items()):
            self.endpoint["inputs"][key.replace("application/json", "application/vnd.example+json")] = copy.deepcopy(value)
        self.assertIn("API-EXAMPLES-REQUEST-COVERAGE", self.codes())

    def test_wrong_response_type_enum_required_or_unknown_fields_fail(self):
        original = copy.deepcopy(self.endpoint["cases"][0]["response"])
        for defect in ("type", "required", "extra", "length", "null"):
            with self.subTest(defect=defect):
                response = copy.deepcopy(original)
                if defect == "type":
                    response["body"]["id"] = "42"
                elif defect == "required":
                    response["body"].pop("name")
                elif defect == "extra":
                    response["body"]["internal"] = True
                elif defect == "length":
                    response["body"]["name"] = "x" * 121
                else:
                    response["body"]["name"] = None
                self.endpoint["cases"][0]["response"] = response
                self.assertIn("API-EXAMPLES-SCHEMA", self.codes())

    def test_request_valid_flag_cannot_hide_invalid_success(self):
        case = self.endpoint["cases"][0]
        case["request"]["body"]["name"] = ""
        self.recurl(case)
        self.assertIn("API-EXAMPLES-REQUEST", self.codes())
        case["request_valid"] = False
        self.assertIn("API-EXAMPLES-REQUEST", self.codes())

    def test_curl_must_match_structured_method_headers_body_and_url(self):
        original = self.endpoint["cases"][0]["curl"]
        for changed in (original.replace("POST", "GET"), original.replace("Demo widget", "Different"),
                        original.replace("application/json", "text/plain"), original.replace("/widgets", "/other"),
                        original.replace("127.0.0.1", "example.invalid"), original + " --config /tmp/anything",
                        original + " ; touch should-never-exist"):
            with self.subTest(command=changed):
                self.endpoint["cases"][0]["curl"] = changed
                self.assertIn("API-EXAMPLES-CURL", self.codes())
        self.assertFalse((self.root / "should-never-exist").exists())

    def test_boolean_and_integer_curl_values_are_not_interchangeable(self):
        schema = self.operation["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"]["quantity"] = {"type": "integer", "minimum": 1}
        self.endpoint["inputs"]["body:application/json:/quantity"] = {
            "description": "Integer quantity", "omitted": "Optional; this fixture defaults to one.",
            "constraints": "Integer at least one", "example": 1}
        case = self.endpoint["cases"][0]
        case["request"]["body"]["quantity"] = 1
        self.recurl(case)
        case["curl"] = case["curl"].replace('"quantity": 1', '"quantity": true')
        self.assertIn("API-EXAMPLES-CURL", self.codes())

    def test_protected_endpoint_can_supply_exact_auth_rejection_and_success_samples(self):
        self.operation.pop("security")
        self.spec["security"] = [{"bearerAuth": []}]
        self.spec["components"] = {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
        self.endpoint["security"] = self.spec["security"]
        self.endpoint["permissions"] = "Bearer-authenticated caller; actual role checks need policy review."
        denied = copy.deepcopy(self.endpoint["cases"][0])
        denied["id"] = "unauthenticated"
        denied["response"] = {"status": 401, "headers": {"Content-Type": "application/problem+json"},
                              "body": {"code": "AUTH_REQUIRED", "status": 401, "detail": "Authentication required."}}
        self.operation["responses"]["401"] = copy.deepcopy(self.operation["responses"]["422"])
        properties = self.operation["responses"]["401"]["content"]["application/problem+json"]["schema"]["properties"]
        properties["code"]["enum"], properties["status"]["enum"] = ["AUTH_REQUIRED"], [401]
        self.endpoint["cases"].append(denied)
        self.endpoint["applicability"]["unauthenticated"] = {"cases": ["unauthenticated"]}
        self.endpoint["cases"][0]["request"]["headers"]["Authorization"] = "Bearer <TEST_TOKEN>"
        self.recurl(self.endpoint["cases"][0])
        self.assertEqual(self.check()[0], 0)

    def test_bodyless_and_head_responses_have_no_json_body(self):
        self.bodyless()
        self.assertEqual(self.check()[0], 0)
        self.endpoint["cases"][0]["response"]["body"] = None
        self.assertIn("API-EXAMPLES-BODY", self.codes())

    def test_head_contract_can_describe_get_representation_without_sending_body(self):
        self.bodyless("HEAD", 200)
        self.operation["responses"]["200"]["content"] = {"application/json": {"schema": {"type": "object"}}}
        self.assertEqual(self.check()[0], 0)

    def test_bodyless_headers_are_still_required_and_checked(self):
        self.bodyless()
        self.operation["responses"]["204"]["headers"] = {"ETag": {"schema": {"type": "string"}}}
        self.assertIn("API-EXAMPLES-HEADER", self.codes())

    def test_numeric_response_headers_validate_as_wire_encoded_primitives(self):
        self.bodyless()
        self.operation["responses"]["204"]["headers"] = {"X-Count": {"schema": {"type": "integer", "minimum": 0}}}
        self.endpoint["cases"][0]["response"]["headers"]["X-Count"] = "20"
        self.assertEqual(self.check()[0], 0)
        self.endpoint["cases"][0]["response"]["headers"]["X-Count"] = "invalid"
        self.assertIn("API-EXAMPLES-HEADER", self.codes())

    def test_redirect_only_endpoint_can_document_its_bodyless_success(self):
        self.bodyless("GET", 302)
        self.assertEqual(self.check()[0], 0)

    def test_placeholder_policy_descriptions_cannot_pass_as_documentation(self):
        self.endpoint["permissions"] = "TBD"
        self.assertIn("API-EXAMPLES-PLACEHOLDER", self.codes())

    def test_security_inheritance_cannot_be_replaced_by_public_declaration(self):
        self.operation.pop("security")
        self.spec["security"] = [{"bearerAuth": []}]
        self.spec["components"] = {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
        self.assertIn("API-EXAMPLES-SECURITY", self.codes())
        self.endpoint["security"] = self.spec["security"]
        rules = self.codes()
        self.assertIn("API-EXAMPLES-AUTH", rules)
        self.assertIn("API-EXAMPLES-APPLICABILITY", rules)

    def test_schema_versions_references_and_media_fail_closed(self):
        original = copy.deepcopy(self.spec)
        for defect in ("version", "external", "missing", "recursive", "keyword", "format", "media"):
            with self.subTest(defect=defect):
                self.spec = copy.deepcopy(original)
                schema = self.spec["paths"]["/widgets"]["post"]["requestBody"]["content"]["application/json"]["schema"]
                if defect == "version":
                    self.spec["openapi"] = "9.0.0"
                elif defect in {"external", "missing", "recursive"}:
                    schema.clear()
                    schema["$ref"] = "https://example.invalid/schema" if defect == "external" else "#/missing"
                    if defect == "recursive":
                        schema["$ref"] = "#/components/schemas/Loop"
                        self.spec["components"] = {"schemas": {"Loop": {"$ref": "#/components/schemas/Loop"}}}
                elif defect == "keyword":
                    schema["unevaluatedProperties"] = False
                elif defect == "format":
                    schema["format"] = "unsupported-private-format"
                else:
                    content = self.spec["paths"]["/widgets"]["post"]["requestBody"]["content"]
                    content["multipart/form-data"] = content.pop("application/json")
                code, payload = self.check()
                self.assertEqual((code, payload["gate_result"]), (4, "blocked"), payload)

    def test_invalid_document_paths_anchors_symlinks_and_json_are_rejected(self):
        self.endpoint["documentation"] = "docs/api.md#does-not-exist"
        self.assertIn("API-EXAMPLES-ANCHOR", self.codes())
        for reference in ("../outside.md", "credentials.json", "docs/missing.md"):
            self.endpoint["documentation"] = reference
            self.assertEqual(self.check()[0], 2)
        outside = make_temp_dir(self)
        write(outside, "outside.md", "outside")
        (self.root / "docs/link.md").symlink_to(outside / "outside.md")
        self.endpoint["documentation"] = "docs/link.md"
        self.assertEqual(self.check()[0], 2)
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{bad'):
            with self.assertRaises(UsageError):
                load_json(value)

    def test_locally_verified_needs_run_test_and_capture_not_just_a_claim(self):
        self.endpoint["cases"][0]["verification"] = {"status": "locally-verified"}
        self.assertIn("API-EXAMPLES-EVIDENCE", self.codes())

    def test_real_runner_capture_links_and_tampering_is_detected(self):
        write(self.root, "app.py", '''def create_widget(body):
    return {"status": 201, "headers": {"Content-Type": "application/json", "Location": "/widgets/42"},
            "body": {"id": 42, "name": body["name"], "note": body.get("note")}}
''')
        self.run_id = run_cli_json("run", "start", "--repo", str(self.root), "--risk", "R1")[1]["run_id"]
        relative = f".devskills/runs/{self.run_id}/artifacts/created.json"
        reference = "tests/test_api.py::Widgets::test_create"
        case = self.endpoint["cases"][0]
        case["verification"] = {"status": "locally-verified", "test": reference, "check": "tests.unit", "capture": relative}
        write(self.root, "tests/test_api.py", '''import json
import unittest
from pathlib import Path
from app import create_widget
class Widgets(unittest.TestCase):
    def test_create(self):
        case = json.loads(Path("docs/api-examples.json").read_text())["endpoints"][0]["cases"][0]
        response = create_widget(case["request"]["body"])
        self.assertEqual(response, case["response"])
        capture = {"case_id": case["id"], "test": case["verification"]["test"], "method": "POST", "path": "/widgets",
                   "request": case["request"], "response": response}
        Path(case["verification"]["capture"]).write_text(json.dumps(capture))
''')
        write(self.root, "run_one.py", '''import importlib.util
import sys
import unittest
from xml.etree.ElementTree import Element, SubElement, ElementTree
spec = importlib.util.spec_from_file_location("tests.test_api", "tests/test_api.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = unittest.TextTestRunner().run(unittest.TestSuite([module.Widgets("test_create")]))
root = Element("testsuite")
case = SubElement(root, "testcase", file="tests/test_api.py", classname="tests.test_api.Widgets", name="test_create")
if not result.wasSuccessful():
    SubElement(case, "failure")
ElementTree(root).write(".devskills/report.xml", encoding="unicode")
sys.exit(0 if result.wasSuccessful() else 1)
''')
        self.save()
        commit_all(self.root)
        result = run_cli("run-tests", "--repo", str(self.root), "--run", self.run_id, "--json", "--capture", relative,
                         "--junit", ".devskills/report.xml", "--", sys.executable, "run_one.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # check() rewrites the same bytes; no source state change is introduced.
        code, payload = self.check()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["details"]["endpoints"][0]["linked_local_evidence"], 1)
        capture = self.root / relative
        original = capture.read_text()
        capture.write_text(original + " ")
        self.assertIn("API-EXAMPLES-EVIDENCE", self.codes())

    def test_roster_requires_sample_check_and_missing_result_blocks(self):
        for tag in ("api", "api_spec"):
            roster = build_default_roster("R1", {tag})
            self.assertTrue(next(entry for entry in roster if entry["check_id"] == "api.examples")["required"])
        from devskills.report import aggregate
        self.assertEqual(aggregate([{"check_id": "api.examples", "required": True}], [], "state", "R1")["overall"], "blocked")


class SchemaAndParserTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional contracts extra")
    def test_nullable_bounds_local_refs_and_directional_fields(self):
        checker = SampleSchemas({"openapi": "3.0.3", "components": {"schemas": {"Number": {
            "type": "number", "minimum": 1, "exclusiveMinimum": True}}}})
        self.assertTrue(checker.errors(1, {"$ref": "#/components/schemas/Number"}, "request"))
        self.assertFalse(checker.errors(2, {"$ref": "#/components/schemas/Number"}, "request"))
        self.assertFalse(checker.errors(None, {"type": "string", "nullable": True}, "response"))
        schema = {"type": "object", "required": ["id", "secret"], "properties": {
            "id": {"type": "integer", "readOnly": True}, "secret": {"type": "string", "writeOnly": True}}}
        self.assertFalse(checker.errors({"secret": "demo"}, schema, "request"))
        self.assertTrue(checker.errors({"id": 1, "secret": "demo"}, schema, "request"))
        self.assertFalse(checker.errors({"id": 1}, schema, "response"))
        self.assertTrue(checker.errors({"id": 1, "secret": "demo"}, schema, "response"))
        newer = SampleSchemas({"openapi": "3.1.0"})
        self.assertFalse(newer.errors(None, {"type": ["string", "null"]}, "request"))

    def test_missing_optional_schema_dependency_blocks(self):
        import builtins
        original = builtins.__import__
        def without_schema(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("fixture: unavailable")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_schema), self.assertRaises(SpecUnavailable):
            SampleSchemas({"openapi": "3.0.3"})

    def test_curl_rejects_shell_config_files_and_multiple_commands(self):
        for command in ("curl -X POST http://127.0.0.1/a --data @private.json", "curl -K config",
                        "curl -X GET http://127.0.0.1/a && touch marker", "curl -X GET https://example.invalid/a",
                        "curl -X GET http://127.0.0.1/a -H 'X: first' -H 'x: second'"):
            with self.subTest(command=command), self.assertRaises(UsageError):
                parse_curl(command)

    def test_curl_json_rejects_duplicate_keys_and_nonfinite_values(self):
        for body in ('{"name":"first","name":"last"}', '{"number":NaN}'):
            import shlex
            command = shlex.join(["curl", "-X", "POST", "http://127.0.0.1/a", "--data-raw", body])
            with self.subTest(body=body), self.assertRaises(UsageError):
                parse_curl(command)

    def test_curl_shell_expansion_is_rejected_but_quoted_literal_data_is_allowed(self):
        command = 'curl -X GET http://127.0.0.1/a --header "X: $(touch marker)"'
        with self.assertRaises(UsageError):
            parse_curl(command)
        parsed = parse_curl("curl -X GET http://127.0.0.1/a --header 'X: $literal'")
        self.assertEqual(parsed["headers"]["x"], "$literal")

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "optional YAML parser")
    def test_duplicate_yaml_keys_cannot_hide_an_endpoint(self):
        from pathlib import Path
        with self.assertRaises(UsageError):
            load_contract("openapi: 3.0.3\npaths: {}\npaths: {}\n", Path("openapi.yaml"))

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional contracts extra")
    def test_complex_regex_blocks_before_unbounded_evaluation(self):
        checker = SampleSchemas({"openapi": "3.0.3"})
        with self.assertRaises(SpecUnavailable):
            checker.errors("a" * 10000 + "!", {"type": "string", "pattern": "^(a+)+$"}, "request")

    def test_capture_missing_or_stale_blocks_even_with_exit_zero(self):
        root = make_temp_dir(self)
        write(root, "stale.json", "{}")
        os.utime(root / "stale.json", (time.time() - 60, time.time() - 60))
        for capture in ("missing.json", "stale.json"):
            result = run_cli("run-tests", "--repo", str(root), "--json", "--capture", capture,
                             "--", sys.executable, "-c", "print('ok')")
            self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        result = run_cli("run-tests", "--repo", str(root), "--json", "--capture", "../outside.json",
                         "--", sys.executable, "-c", "print('must not run')")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
