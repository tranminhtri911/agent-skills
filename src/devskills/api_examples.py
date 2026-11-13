"""API-011: offline endpoint/sample completeness, schema and evidence checks.

The supplied OpenAPI document defines scope; this command never imports an app,
executes curl, resolves remote references or claims business semantics from text.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from devskills.api_contract import HTTP_METHODS, SpecUnavailable
from devskills.api_sample_curl import parse_curl
from devskills.api_sample_schema import SampleSchemas
from devskills.fsutil import current_repo_state, is_secret_file, is_within, read_text_limited, resolve_repo_root, sha256_file
from devskills.models import EXEC_COMPLETED, GATE_BLOCKED, GATE_FAIL, GATE_PASS, CheckResult, Finding, UsageError
from devskills.output import emit_result, format_findings
from devskills.runs import run_dir_checked, validate_check_id
from devskills.secrets_scan import scan_text
from devskills.trace import evaluate_criterion

TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
CATEGORIES = {"validation": {400, 422}, "unauthenticated": {401, 403, 404}, "forbidden": {403, 404},
              "not_found": {404}, "conflict": {409, 422}, "rate_limit": {429}}
MAX_INPUT_BYTES = 2 * 1024 * 1024


def _object(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or list(properties), "additionalProperties": False}


HEADERS = {"type": "object", "additionalProperties": {"type": "string"}}
REQUEST = _object({"path": {"type": "object"}, "query": {"type": "object"}, "headers": HEADERS,
                   "body": {}, "body_raw": {"type": "string"}}, ["path", "query", "headers"])
RESPONSE = _object({"status": {"type": "integer", "minimum": 200, "maximum": 599}, "headers": HEADERS, "body": {}},
                   ["status", "headers"])
CASE = _object({"id": TEXT, "trigger": TEXT, "curl": TEXT, "request": REQUEST, "response": RESPONSE,
                "request_valid": {"type": "boolean"}, "assertions": {"type": "array", "items": TEXT, "minItems": 1},
                "verification": _object({"status": {"enum": ["illustrative", "schema-validated", "locally-verified"]},
                    "test": TEXT, "check": TEXT, "capture": TEXT}, ["status"])})
APPLICABILITY = {"oneOf": [_object({"cases": {"type": "array", "items": TEXT, "minItems": 1, "uniqueItems": True}}),
                            _object({"reason": TEXT})]}
ENDPOINT = _object({"method": {"enum": [method.upper() for method in HTTP_METHODS]}, "path": TEXT,
    "documentation": TEXT, "sources": {"type": "array", "items": TEXT, "minItems": 1, "uniqueItems": True},
    "purpose": TEXT, "permissions": TEXT, "security": {"type": "array", "items": {"type": "object"}},
    "inputs": {"type": "object", "additionalProperties": _object({"description": TEXT, "omitted": TEXT,
        "constraints": TEXT, "example": {}})},
    "effects": _object({key: TEXT for key in ("changes", "preserves", "failure", "external", "transaction", "retry")}),
    "applicability": _object({key: APPLICABILITY for key in CATEGORIES}),
    "cases": {"type": "array", "items": CASE, "minItems": 1, "maxItems": 200}})
MANIFEST_SCHEMA = _object({"format_version": {"const": 1}, "base_url": TEXT,
    "endpoints": {"type": "array", "items": ENDPOINT, "minItems": 1, "maxItems": 1000}})


def read_local(root: Path, reference: str) -> tuple[Path, str]:
    """Read bounded repository-owned text; reject secrets, symlinks and escapes before reading."""
    relative = reference.split("#", 1)[0]
    path = root / relative
    if not relative or is_secret_file(relative) or not is_within(path, root) or path.is_symlink():
        raise UsageError("sample references must be non-secret files inside the repository")
    text = read_text_limited(path, MAX_INPUT_BYTES)
    if text is None:
        raise UsageError("sample reference is missing, unreadable, binary or over 2 MiB")
    return path, text


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise UsageError("duplicate JSON object key in sample input")
        result[key] = value
    return result


def load_json(text: str) -> Any:
    """Strict JSON, rejecting duplicate keys and non-finite numbers instead of silently accepting them."""
    def invalid(_value: str) -> None:
        raise UsageError("non-finite JSON values are not supported")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)
    except (ValueError, RecursionError) as error:
        raise UsageError("sample JSON is invalid or exceeds the nesting limit") from error


def load_contract(text: str, path: Path) -> Any:
    """Read JSON or strict safe YAML; duplicate keys cannot hide an operation."""
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        return load_json(text)
    try:
        import yaml
    except ImportError as error:
        raise SpecUnavailable("YAML contract needs PyYAML; export JSON when it is unavailable") from error

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        pairs = [(loader.construct_object(key, deep=True), loader.construct_object(value, deep=True)) for key, value in node.value]
        return _pairs(pairs)

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    loader = UniqueLoader(text)
    try:
        return loader.get_single_data()
    except (yaml.YAMLError, TypeError, RecursionError) as error:
        raise UsageError("invalid, recursive or unsupported YAML contract; export JSON") from error
    finally:
        loader.dispose()


def headers(raw: dict) -> dict[str, str]:
    result = {name.lower(): value for name, value in raw.items()}
    if len(result) != len(raw) or any("\n" in name + value or "\r" in name + value for name, value in raw.items()):
        raise UsageError("headers must have unique case-insensitive names and no line breaks")
    return result


def same_json(left: Any, right: Any) -> bool:
    """Compare JSON types as well as values (Python's True == 1 is insufficient)."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


class ExamplesCheck:
    """Check one supplied contract and its exact method/path inventory; findings never echo payloads."""

    def __init__(self, root: Path, spec: dict, run_id: str | None):
        self.root, self.spec, self.run_id = root, spec, run_id
        self.schemas = SampleSchemas(spec)
        self.findings: list[Finding] = []
        self.rows: list[dict] = []

    def add(self, rule: str, location: str, message: str) -> None:
        self.findings.append(Finding("API-EXAMPLES-" + rule, "high", location + ": " + message))

    def validate(self, manifest: dict) -> None:
        """Require one complete manifest entry for every operation in the supplied contract."""
        structural = list(self.schemas.library.Draft202012Validator(MANIFEST_SCHEMA).iter_errors(manifest))
        if structural:
            for error in structural[:20]:
                self.add("FORMAT", "/".join(str(part) for part in error.path), "manifest violates " + str(error.validator))
            return
        base = urlsplit(manifest["base_url"])
        if base.scheme not in {"http", "https"} or base.hostname not in {"localhost", "127.0.0.1", "::1"} or base.query or base.fragment or base.username:
            raise UsageError("base_url must be a literal loopback HTTP(S) URL without credentials, query or fragment")
        operations = {}
        for path, raw_item in (self.spec.get("paths") or {}).items():
            item = self.schemas.resolve(raw_item)
            if not isinstance(item, dict) or not path.startswith("/"):
                raise SpecUnavailable("invalid OpenAPI path item")
            for method in HTTP_METHODS:
                if method in item:
                    operations[(method.upper(), path)] = (item, item[method])
        if not operations:
            self.add("EMPTY", "OpenAPI", "no HTTP operations to verify")
        seen = set()
        for endpoint in manifest["endpoints"]:
            key = endpoint["method"], endpoint["path"]
            where = " ".join(key)
            if key in seen:
                self.add("DUPLICATE", where, "duplicate endpoint entry")
            seen.add(key)
            if key not in operations:
                self.add("UNKNOWN", where, "method/path does not exist in the supplied OpenAPI contract")
                continue
            self.endpoint(endpoint, *operations[key], manifest["base_url"])
        for key in operations.keys() - seen:
            self.add("MISSING", " ".join(key), "endpoint has no examples entry")

    def endpoint(self, endpoint: dict, item: dict, operation: dict, base_url: str) -> None:
        """Compare an endpoint's documentation, security, fields and cases with its contract."""
        where = endpoint["method"] + " " + endpoint["path"]
        before = len(self.findings)
        explanations = [endpoint["purpose"], endpoint["permissions"], *endpoint["effects"].values()]
        explanations += [entry[key] for entry in endpoint["inputs"].values() for key in ("description", "omitted", "constraints")]
        explanations += [entry["reason"] for entry in endpoint["applicability"].values() if "reason" in entry]
        if any(re.fullmatch(r"\s*(?:<[^>]+>|TODO|TBD|N/?A|\.{3})\s*", value, re.IGNORECASE) for value in explanations):
            self.add("PLACEHOLDER", where, "documentation contains an unexplained placeholder/N/A")
        for reference in [endpoint["documentation"], *endpoint["sources"]]:
            if Path(reference.split("#", 1)[0]).is_absolute():
                raise UsageError("documentation/source references must be repository-relative")
            _path, text = read_local(self.root, reference)
            if not text.strip():
                self.add("DOCUMENT", where, "source/documentation reference is empty")
            if "#" in reference:
                anchor = unquote(reference.partition("#")[2])
                titles = re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE)
                anchors = {re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-") for title in titles}
                if anchor not in anchors and f'id="{anchor}"' not in text:
                    self.add("ANCHOR", where, "documentation anchor does not exist")
        expected_security = operation.get("security", self.spec.get("security", []))
        if endpoint["security"] != expected_security:
            self.add("SECURITY", where, "declared security differs from effective OpenAPI security")
        self._security_defined(expected_security)
        parameters = {}
        for raw in item.get("parameters", []) + operation.get("parameters", []):
            param = self.schemas.resolve(raw)
            if not isinstance(param, dict) or param.get("in") not in {"path", "query", "header", "cookie"} or not param.get("name"):
                raise SpecUnavailable("invalid or unsupported OpenAPI parameter")
            parameters[(param["in"], param["name"])] = param
        body = self.schemas.resolve(operation.get("requestBody", {}))
        expected_inputs = {location + ":" + name: param.get("schema", {}) for (location, name), param in parameters.items()}
        for media, definition in body.get("content", {}).items():
            self._json_media(media)
            expected_inputs.update(self.schemas.fields(definition.get("schema", {}), "body:" + media + ":"))
        if set(endpoint["inputs"]) != set(expected_inputs):
            self.add("INPUTS", where, "input documentation must exactly cover parameters and nested request schema fields")
        for key in set(expected_inputs) & set(endpoint["inputs"]):
            errors = self.schemas.errors(endpoint["inputs"][key]["example"], expected_inputs[key], "request")
            if errors:
                self.add("INPUT-EXAMPLE", where + " " + key, "field example fails schema: " + "; ".join(errors))
        responses = {str(code): self.schemas.resolve(value) for code, value in operation.get("responses", {}).items()}
        if not responses:
            self.add("RESPONSES", where, "operation declares no responses")
        seen_cases: dict[str, dict] = {}
        covered: set[tuple[str, str]] = set()
        request_media_seen: set[str] = set()
        local_count = 0
        for case in endpoint["cases"]:
            if case["id"] in seen_cases:
                self.add("DUPLICATE", where, "duplicate case id")
            seen_cases[case["id"]] = case
            case_where = where + " / " + case["id"]
            request_headers = headers(case["request"]["headers"])
            for name, value in request_headers.items():
                if name in {"authorization", "cookie", "x-api-key"} and value and not re.search(r"<[^>]+>|REDACTED", value):
                    self.add("CREDENTIAL", case_where, "credential-bearing samples must use redacted synthetic placeholders")
            for requirement in expected_security:
                schemes = (self.spec.get("components") or {}).get("securitySchemes", {})
                for name in requirement:
                    scheme = self.schemas.resolve(schemes[name])
                    if scheme.get("type") == "apiKey" and scheme.get("in") in {"query", "header"}:
                        values = request_headers if scheme["in"] == "header" else case["request"]["query"]
                        key = scheme["name"].lower() if scheme["in"] == "header" else scheme["name"]
                        value = values.get(key)
                        if value and (not isinstance(value, str) or not re.search(r"<[^>]+>|REDACTED", value)):
                            self.add("CREDENTIAL", case_where, "API-key samples must use redacted synthetic placeholders")
            try:
                self._curl(case, endpoint, base_url, request_headers)
            except UsageError as error:
                self.add("CURL", case_where, str(error))
            request_errors = self._request(case["request"], parameters, body, request_headers)
            if case["request_valid"] == bool(request_errors):
                self.add("REQUEST", case_where, "request_valid does not match schema/parameter validation")
            if case["response"]["status"] < 400:
                if not case["request_valid"]:
                    self.add("REQUEST", case_where, "success example cannot use an intentionally invalid request")
                self._authentication(expected_security, case["request"], request_headers, case_where)
                if "body" in case["request"] and case["request_valid"]:
                    request_media_seen.add(request_headers.get("content-type", "").split(";", 1)[0].strip())
            covered.add(self._response(case["response"], responses, endpoint["method"], case_where))
            if case["verification"]["status"] == "locally-verified":
                if self._evidence(case, endpoint, case_where):
                    local_count += 1
            elif set(case["verification"]) != {"status"}:
                self.add("EVIDENCE", case_where, "unexecuted samples cannot attach claims of local execution")
        if not any(case["response"]["status"] < 400 for case in seen_cases.values()):
            self.add("SUCCESS", where, "at least one successful sample is required")
        for media in body.get("content", {}):
            if media not in request_media_seen:
                self.add("REQUEST-COVERAGE", where, "missing successful request sample for " + media)
        for code, response in responses.items():
            content = {} if endpoint["method"] == "HEAD" or code in {"204", "304"} else response.get("content", {})
            for media in content or {"": {}}:
                if (code, media) not in covered:
                    self.add("COVERAGE", where, "missing response example for " + code + " " + media)
        self._applicability(endpoint, seen_cases, responses, expected_security, where)
        self.rows.append({"method": endpoint["method"], "path": endpoint["path"], "cases": len(seen_cases),
                          "linked_local_evidence": local_count, "result": "fail" if len(self.findings) > before else "pass"})

    @staticmethod
    def _json_media(media: str) -> None:
        if "*" in media or (media != "application/json" and not media.endswith("+json")):
            raise SpecUnavailable("non-JSON media needs a reviewed sample adapter; no automatic pass")

    def _header_value(self, value: str, schema: dict) -> Any:
        """Decode primitive header values before validating their logical OpenAPI type."""
        resolved = self.schemas.resolve(schema)
        kind = resolved.get("type") if isinstance(resolved, dict) else None
        try:
            if kind == "integer":
                return int(value)
            if kind == "number":
                number = float(value)
                return number if math.isfinite(number) else value
            if kind == "boolean" and value in {"true", "false"}:
                return value == "true"
            if kind in {"array", "object"}:
                raise SpecUnavailable("structured response header needs a reviewed serialization adapter")
        except ValueError:
            return value
        return value

    def _security_defined(self, security: list) -> None:
        schemes = (self.spec.get("components") or {}).get("securitySchemes", {})
        for requirement in security:
            if not isinstance(requirement, dict) or any(not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes)
                                                       for scopes in requirement.values()):
                raise SpecUnavailable("invalid OpenAPI security requirement scopes")
            for name in requirement:
                if name not in schemes:
                    raise SpecUnavailable("security requirement references an undefined scheme")

    def _curl(self, case: dict, endpoint: dict, base_url: str, request_headers: dict) -> None:
        parsed = parse_curl(case["curl"])
        path = endpoint["path"]
        names = set(re.findall(r"\{([^}]+)\}", path))
        if set(case["request"]["path"]) != names:
            raise UsageError("path fixture keys do not match route placeholders")
        for name, value in case["request"]["path"].items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        expected = base_url.rstrip("/") + path
        actual = urlsplit(parsed["url"])
        if parsed["method"] != endpoint["method"] or actual._replace(query="").geturl() != expected:
            raise UsageError("curl method/URL differs from the declared endpoint and fixtures")
        query = {name: [str(item).lower() if isinstance(item, bool) else str(item) for item in (value if isinstance(value, list) else [value])]
                 for name, value in case["request"]["query"].items()}
        if parsed["query"] != query or parsed["headers"] != request_headers:
            raise UsageError("curl headers/query differ from the declared sample")
        for key in ("body", "body_raw"):
            if (key in parsed) != (key in case["request"]) or (key in parsed and not same_json(parsed[key], case["request"][key])):
                raise UsageError("curl body differs from the declared sample")

    def _request(self, request: dict, parameters: dict, body: dict, request_headers: dict) -> list[str]:
        errors = []
        locations = {"path": request["path"], "query": request["query"], "header": request_headers}
        for (location, name), param in parameters.items():
            if location == "cookie" or "content" in param:
                raise SpecUnavailable("cookie/content parameters need a reviewed sample adapter")
            values = locations[location]
            key = name.lower() if location == "header" else name
            if key not in values:
                if param.get("required") or location == "path":
                    errors.append(location + ": missing required parameter")
                continue
            schema = param.get("schema", {})
            if param.get("style", "simple" if location in {"path", "header"} else "form") not in {"simple", "form"}:
                raise SpecUnavailable("parameter serialization style needs a reviewed adapter")
            resolved_schema = self.schemas.resolve(schema)
            param_type = resolved_schema.get("type") if isinstance(resolved_schema, dict) else None
            if param_type == "object" or (param_type == "array" and (location != "query" or param.get("explode") is False)):
                raise SpecUnavailable("complex parameter serialization needs a reviewed adapter")
            value = values[key]
            if location == "header":
                schema_type = param_type
                try:
                    value = int(value) if schema_type == "integer" else float(value) if schema_type == "number" else value
                except ValueError:
                    errors.append("invalid header value")
            errors.extend(self.schemas.errors(value, schema, "request"))
        has_body = "body" in request or "body_raw" in request
        if "body" in request and "body_raw" in request:
            errors.append("both JSON and raw body declared")
        if body.get("required") and not has_body:
            errors.append("missing request body")
        if has_body:
            if "body_raw" in request:
                errors.append("malformed JSON request")
            else:
                media = request_headers.get("content-type", "").split(";", 1)[0].strip()
                content = body.get("content", {})
                if media not in content:
                    errors.append("request media not declared")
                else:
                    errors.extend(self.schemas.errors(request["body"], content[media].get("schema", {}), "request"))
        return errors

    def _authentication(self, security: list, request: dict, request_headers: dict, where: str) -> None:
        schemes = (self.spec.get("components") or {}).get("securitySchemes", {})
        if not security or {} in security:
            return
        for requirement in security:
            present = True
            for name in requirement:
                scheme = self.schemas.resolve(schemes[name])
                if scheme.get("type") in {"http", "oauth2", "openIdConnect"}:
                    value = request_headers.get("authorization", "")
                    present &= bool(value) and (not scheme.get("scheme") or value.lower().startswith(scheme["scheme"].lower() + " "))
                elif scheme.get("type") == "apiKey" and scheme.get("in") in {"header", "query"}:
                    present &= bool((request_headers if scheme["in"] == "header" else request["query"]).get(
                        scheme["name"].lower() if scheme["in"] == "header" else scheme["name"]))
                else:
                    raise SpecUnavailable("security scheme needs a reviewed sample adapter")
            if present:
                return
        self.add("AUTH", where, "successful sample lacks credentials required by the contract")

    def _response(self, response: dict, responses: dict, method: str, where: str) -> tuple[str, str]:
        code = str(response["status"])
        key = code if code in responses else code[0] + "XX" if code[0] + "XX" in responses else "default"
        if key not in responses:
            self.add("STATUS", where, "response status is not declared in OpenAPI")
            return code, ""
        definition = responses[key]
        response_headers = headers(response["headers"])
        for name, raw in definition.get("headers", {}).items():
            header = self.schemas.resolve(raw)
            if name.lower() not in response_headers:
                self.add("HEADER", where, "declared response header has no sample: " + name)
            elif self.schemas.errors(self._header_value(response_headers[name.lower()], header.get("schema", {})),
                                     header.get("schema", {}), "response"):
                self.add("HEADER", where, "response header value fails its declared schema")
        if response["status"] == 429 and "retry-after" not in response_headers:
            self.add("HEADER", where, "429 sample must show Retry-After")
        content = definition.get("content", {})
        if method == "HEAD" or response["status"] in {204, 304} or not content:
            if "body" in response:
                self.add("BODY", where, "bodyless response must omit body, including JSON null")
            if content and method != "HEAD":
                self.add("BODY", where, "bodyless status declares response content in the contract")
            return key, ""
        media = response_headers.get("content-type", "").split(";", 1)[0].strip()
        if media not in content or "body" not in response:
            self.add("BODY", where, "response body/Content-Type does not match a declared media type")
            return key, media
        self._json_media(media)
        errors = self.schemas.errors(response["body"], content[media].get("schema", {}), "response")
        if errors:
            self.add("SCHEMA", where, "response fails schema: " + "; ".join(errors))
        if (media == "application/problem+json" and isinstance(response["body"], dict)
                and "status" in response["body"] and response["body"]["status"] != response["status"]):
            self.add("STATUS", where, "Problem Details status disagrees with the HTTP status")
        return key, media

    def _applicability(self, endpoint: dict, cases: dict, responses: dict, security: list, where: str) -> None:
        declared = {int(code) for code in responses if code.isdigit()}
        mandatory = {"unauthenticated": bool(security and {} not in security), "validation": bool(declared & {400, 422}),
                     "forbidden": 403 in declared, "not_found": 404 in declared, "conflict": 409 in declared,
                     "rate_limit": 429 in declared}
        for category, entry in endpoint["applicability"].items():
            if "reason" in entry:
                if mandatory[category]:
                    self.add("APPLICABILITY", where, category + " cannot be N/A for this contract")
                continue
            for case_id in entry["cases"]:
                if case_id not in cases or cases[case_id]["response"]["status"] not in CATEGORIES[category]:
                    self.add("APPLICABILITY", where, category + " references a missing or incompatible case")

    def _evidence(self, case: dict, endpoint: dict, where: str) -> bool:
        verification = case["verification"]
        if not self.run_id or not all(key in verification for key in ("test", "check", "capture")):
            self.add("EVIDENCE", where, "locally-verified needs --run, exact test/check and a captured exchange")
            return False
        run_dir = run_dir_checked(self.root, self.run_id)
        check_id = validate_check_id(verification["check"])
        try:
            _path, check_text = read_local(self.root, str((run_dir / "checks" / (check_id + ".json")).relative_to(self.root)))
            check = load_json(check_text)
            capture_path, text = read_local(self.root, verification["capture"])
            if not is_within(capture_path, run_dir):
                raise UsageError("capture must be inside the current run")
            captured_hashes = (check.get("details") or {}).get("captures") or {}
            if captured_hashes.get(capture_path.resolve().relative_to(self.root).as_posix()) != sha256_file(capture_path):
                raise UsageError("capture was not fingerprinted by the linked runner or changed afterwards; rerun with --capture")
            capture = load_json(text)
            row = evaluate_criterion({"id": case["id"], "evidence": [{"test": verification["test"], "check": check_id}]},
                                     self.root, run_dir, {check_id: check})
            current_state = current_repo_state(self.root)
            if (row["status"] != "verified" or not current_state.get("diff_digest") or check.get("repo_state") != current_state
                    or (check.get("details") or {}).get("profile") not in {"unit_offline", "integration_isolated"}):
                raise UsageError("test evidence is missing, failed, skipped, stale or not isolated locally")
            expected = {"case_id": case["id"], "test": verification["test"], "method": endpoint["method"],
                        "path": endpoint["path"], "request": case["request"], "response": case["response"]}
            if not same_json(capture, expected):
                raise UsageError("captured exchange does not match this exact sample/test")
            start = datetime.fromisoformat(check["started_at"]).timestamp()
            end = datetime.fromisoformat(check["finished_at"]).timestamp() + 1
            if not start <= capture_path.stat().st_mtime <= end:
                raise UsageError("capture was not written during the linked execution")
        except (UsageError, KeyError, ValueError, TypeError, OSError) as error:
            self.add("EVIDENCE", where, str(error) if isinstance(error, UsageError) else "invalid local evidence")
            return False
        return True


def run(args: argparse.Namespace) -> int:
    """Validate static API examples and linked local evidence; never execute sample requests."""
    root = resolve_repo_root(args.repo)
    spec_path, spec_text = read_local(root, args.spec)
    file_path, file_text = read_local(root, args.file)
    manifest = load_json(file_text)
    details: dict[str, Any] = {"spec": str(spec_path.relative_to(root)), "file": str(file_path.relative_to(root)),
        "scope": "all HTTP operations in the supplied OpenAPI document", "network_requests": 0,
        "limitations": "Does not discover omitted app routes or prove policy/business semantics; local records are editable evidence, not independent attestations."}
    findings = scan_text(file_text, str(file_path.relative_to(root)))[0]
    rows = []
    try:
        spec = load_contract(spec_text, spec_path)
        if not isinstance(spec, dict):
            raise UsageError("OpenAPI root must be an object")
        check = ExamplesCheck(root, spec, args.run)
        check.validate(manifest)
        findings += check.findings
        rows = check.rows
        gate = GATE_FAIL if findings else GATE_PASS
    except (SpecUnavailable, RecursionError) as error:
        gate = GATE_BLOCKED
        findings.append(Finding("API-EXAMPLES-UNSUPPORTED", "medium", str(error)))
    details["endpoints"] = rows
    summary = f"{len(rows)} endpoints checked; {len(findings)} findings; no sample requests executed"
    result = CheckResult(check_id=args.check_id, tool="devskills.api-examples", execution_status=EXEC_COMPLETED,
        gate_result=gate, domain_result="sample_contract_checked" if gate == GATE_PASS else "incomplete_or_unverified",
        summary=summary, findings=findings, details=details, evidence_refs=[str(spec_path), str(file_path)])
    return emit_result(args, root, result, ["api-examples: " + summary, *format_findings(findings)])
