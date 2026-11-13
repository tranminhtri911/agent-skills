"""OpenAPI contract diff: find changes that break existing clients (plan §11, API-0xx).

Compares a base spec (a git ref or a file) with the current spec. Request side
and response side are judged in opposite directions: a client may send less
than the server accepts and must read everything the server promises.

Breaking (high):  removed path/method/2xx status, new required request field or
                  parameter, optional -> required in requests, type change,
                  removed request enum value, tightened request constraint,
                  request nullable -> not nullable, removed response field,
                  response required -> optional, response not nullable -> nullable.
Warning (low):    added response enum value (clients with exhaustive switches),
                  removed optional request parameter.

JSON specs need only the standard library; YAML needs PyYAML and is `blocked`
without it. `$ref` to `#/...` is resolved with a cycle guard; `allOf` is merged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from devskills.fsutil import is_within, resolve_repo_root, run_git
from devskills.models import EXEC_COMPLETED, EXEC_NOT_RUN, GATE_BLOCKED, CheckResult, Finding, UsageError, gate_from_findings
from devskills.output import emit_result, format_findings, severity_summary

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head", "trace")
MAX_DEPTH = 12
# (keyword, "tighter" direction): larger minimum or smaller maximum rejects previously valid input.
LOWER_BOUNDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
UPPER_BOUNDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")


class SpecUnavailable(Exception):
    """The spec cannot be parsed in this environment (e.g. YAML without PyYAML)."""


def parse_spec(text: str, name: str) -> dict[str, Any]:
    """Parse JSON, or YAML when PyYAML is installed."""
    if name.endswith(".json") or text.lstrip().startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise UsageError(f"{name}: invalid JSON: {error}") from error
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as error:
        raise SpecUnavailable("YAML spec needs PyYAML (pip install pyyaml) or export the spec as JSON") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise UsageError(f"{name}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise UsageError(f"{name}: spec root must be an object")
    return data


class _Resolver:
    """Resolve local `$ref`s and merge `allOf`, never looping on recursive schemas."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec

    def lookup(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            return {}  # External refs are out of scope; treated as an opaque schema.
        node: Any = self.spec
        for part in ref[2:].split("/"):
            node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
        return node if isinstance(node, dict) else {}

    def schema(self, node: Any, seen: frozenset[str] = frozenset()) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        if "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                return {"$recursive": ref}
            return self.schema(self.lookup(ref), seen | {ref})
        if "allOf" in node:
            merged: dict[str, Any] = {key: value for key, value in node.items() if key != "allOf"}
            properties: dict[str, Any] = dict(merged.get("properties") or {})
            required = set(merged.get("required") or [])
            for part in node["allOf"]:
                resolved = self.schema(part, seen)
                properties.update(resolved.get("properties") or {})
                required.update(resolved.get("required") or [])
                for key, value in resolved.items():
                    if key not in ("properties", "required"):
                        merged.setdefault(key, value)
            merged["properties"], merged["required"] = properties, sorted(required)
            return merged
        return node


def _types(schema: dict[str, Any]) -> tuple[frozenset[str], bool]:
    """(types without null, nullable) for OpenAPI 3.0 `nullable` and 3.1 type arrays."""
    raw = schema.get("type")
    types = set(raw) if isinstance(raw, list) else ({raw} if raw else set())
    nullable = bool(schema.get("nullable")) or "null" in types
    if "properties" in schema and not types:
        types.add("object")
    return frozenset(types - {"null"}), nullable


class ContractDiff:
    """Collects findings while walking both specs."""

    def __init__(self, base: dict[str, Any], current: dict[str, Any]):
        self.base, self.current = _Resolver(base), _Resolver(current)
        self.findings: list[Finding] = []

    def add(self, rule: str, severity: str, location: str, message: str) -> None:
        self.findings.append(Finding(rule_id=rule, severity=severity, message=f"{location}: {message}"))

    def compare_schema(self, old: Any, new: Any, location: str, side: str, depth: int = 0) -> None:
        """side is 'request' or 'response'; the same edit can break one side and be safe on the other."""
        old_schema, new_schema = self.base.schema(old), self.current.schema(new)
        if depth > MAX_DEPTH or "$recursive" in old_schema or "$recursive" in new_schema:
            return
        old_types, old_nullable = _types(old_schema)
        new_types, new_nullable = _types(new_schema)
        if old_types and new_types and old_types != new_types and not (side == "request" and old_types < new_types):
            self.add("API-BREAK-TYPE", "high", location, f"type {sorted(old_types)} -> {sorted(new_types)}")
        if side == "request" and old_nullable and not new_nullable:
            self.add("API-BREAK-NULLABLE", "high", location, "request field no longer accepts null")
        if side == "response" and not old_nullable and new_nullable:
            self.add("API-BREAK-NULLABLE", "high", location, "response field may now be null")
        old_enum, new_enum = old_schema.get("enum"), new_schema.get("enum")
        if isinstance(old_enum, list) and isinstance(new_enum, list):
            removed = [value for value in old_enum if value not in new_enum]
            added = [value for value in new_enum if value not in old_enum]
            if side == "request" and removed:
                self.add("API-BREAK-ENUM", "high", location, f"request enum values removed: {removed[:5]}")
            if side == "response" and added:
                self.add("API-WARN-ENUM", "low", location, f"response enum values added: {added[:5]} (exhaustive client switches)")
        elif side == "request" and new_enum and not old_enum:
            self.add("API-BREAK-ENUM", "high", location, "request field is now restricted to an enum")
        if side == "request":
            self._compare_constraints(old_schema, new_schema, location)
        old_props, new_props = old_schema.get("properties") or {}, new_schema.get("properties") or {}
        old_required, new_required = set(old_schema.get("required") or []), set(new_schema.get("required") or [])
        for name, old_prop in old_props.items():
            child = f"{location}.{name}"
            if name not in new_props:
                if side == "response":
                    self.add("API-BREAK-FIELD-REMOVED", "high", child, "response field removed")
                continue
            if side == "request" and name not in old_required and name in new_required:
                self.add("API-BREAK-REQUIRED", "high", child, "request field became required")
            if side == "response" and name in old_required and name not in new_required:
                self.add("API-BREAK-REQUIRED", "high", child, "response field is no longer guaranteed")
            self.compare_schema(old_prop, new_props[name], child, side, depth + 1)
        for name in new_props.keys() - old_props.keys():
            if side == "request" and name in new_required:
                self.add("API-BREAK-REQUIRED", "high", f"{location}.{name}", "new required request field")
        if "items" in old_schema and "items" in new_schema:
            self.compare_schema(old_schema["items"], new_schema["items"], f"{location}[]", side, depth + 1)

    def _compare_constraints(self, old: dict[str, Any], new: dict[str, Any], location: str) -> None:
        for keyword in LOWER_BOUNDS + UPPER_BOUNDS:
            old_value, new_value = old.get(keyword), new.get(keyword)
            if not isinstance(new_value, (int, float)) or isinstance(new_value, bool):
                continue
            tighter = (old_value is None or (isinstance(old_value, (int, float)) and
                       (new_value > old_value if keyword in LOWER_BOUNDS else new_value < old_value)))
            if tighter:
                self.add("API-BREAK-CONSTRAINT", "high", location, f"{keyword} {old_value} -> {new_value}")
        if new.get("pattern") and new.get("pattern") != old.get("pattern"):
            self.add("API-BREAK-CONSTRAINT", "high", location, "pattern added or changed")

    def _parameters(self, resolver: _Resolver, path_item: dict[str, Any], operation: dict[str, Any]) -> dict[tuple[str, str], dict]:
        merged: dict[tuple[str, str], dict] = {}
        for raw in list(path_item.get("parameters") or []) + list(operation.get("parameters") or []):
            parameter = resolver.lookup(raw["$ref"]) if isinstance(raw, dict) and "$ref" in raw else raw
            if isinstance(parameter, dict) and parameter.get("name"):
                merged[(parameter.get("in", "query"), parameter["name"])] = parameter
        return merged

    @staticmethod
    def _json_schema(container: dict[str, Any] | None) -> Any:
        content = (container or {}).get("content") or {}
        for media_type, body in content.items():
            if "json" in media_type and isinstance(body, dict):
                return body.get("schema")
        return next((body.get("schema") for body in content.values() if isinstance(body, dict)), None)

    def run(self) -> list[Finding]:
        old_paths = self.base.spec.get("paths") or {}
        new_paths = self.current.spec.get("paths") or {}
        for path, old_item in old_paths.items():
            if path not in new_paths:
                self.add("API-BREAK-PATH-REMOVED", "high", path, "path removed")
                continue
            new_item = new_paths[path]
            for method in HTTP_METHODS:
                if method not in old_item:
                    continue
                where = f"{method.upper()} {path}"
                if method not in new_item:
                    self.add("API-BREAK-METHOD-REMOVED", "high", where, "operation removed")
                    continue
                self._compare_operation(old_item, new_item, old_item[method], new_item[method], where)
        return self.findings

    def _compare_operation(self, old_item: dict, new_item: dict, old_op: dict, new_op: dict, where: str) -> None:
        old_params = self._parameters(self.base, old_item, old_op)
        new_params = self._parameters(self.current, new_item, new_op)
        for key, new_param in new_params.items():
            old_param = old_params.get(key)
            label = f"{where} {key[0]}:{key[1]}"
            if old_param is None:
                if new_param.get("required"):
                    self.add("API-BREAK-REQUIRED", "high", label, "new required parameter")
                continue
            if new_param.get("required") and not old_param.get("required"):
                self.add("API-BREAK-REQUIRED", "high", label, "parameter became required")
            self.compare_schema(old_param.get("schema"), new_param.get("schema"), label, "request")
        for key, old_param in old_params.items():
            if key not in new_params:
                self.add("API-WARN-PARAM-REMOVED", "low", f"{where} {key[0]}:{key[1]}",
                         "parameter removed (clients still sending it are ignored or rejected)")
        old_body = self.base.lookup(old_op["requestBody"]["$ref"]) if "$ref" in (old_op.get("requestBody") or {}) else old_op.get("requestBody")
        new_body = self.current.lookup(new_op["requestBody"]["$ref"]) if "$ref" in (new_op.get("requestBody") or {}) else new_op.get("requestBody")
        if new_body and new_body.get("required") and not (old_body or {}).get("required"):
            self.add("API-BREAK-REQUIRED", "high", f"{where} body", "request body became required")
        if old_body and new_body:
            self.compare_schema(self._json_schema(old_body), self._json_schema(new_body), f"{where} body", "request")
        old_responses, new_responses = old_op.get("responses") or {}, new_op.get("responses") or {}
        for status, old_response in old_responses.items():
            label = f"{where} -> {status}"
            if status not in new_responses:
                if str(status).startswith("2"):
                    self.add("API-BREAK-STATUS-REMOVED", "high", label, "success response removed")
                continue
            old_resolved = self.base.lookup(old_response["$ref"]) if "$ref" in old_response else old_response
            new_raw = new_responses[status]
            new_resolved = self.current.lookup(new_raw["$ref"]) if "$ref" in new_raw else new_raw
            old_schema, new_schema = self._json_schema(old_resolved), self._json_schema(new_resolved)
            if old_schema is not None and new_schema is not None:
                self.compare_schema(old_schema, new_schema, label, "response")
            elif old_schema is not None:
                self.add("API-BREAK-FIELD-REMOVED", "high", label, "response body removed")


def diff_specs(base: dict[str, Any], current: dict[str, Any]) -> list[Finding]:
    """Return breaking-change and warning findings between two parsed specs."""
    return ContractDiff(base, current).run()


def _read_base(repo_root: Path, spec_rel: str, base_ref: str | None, base_file: str | None) -> tuple[str, str]:
    if base_file:
        path = Path(base_file)
        return path.read_text(encoding="utf-8"), str(path)
    output = run_git(repo_root, ["show", f"{base_ref}:{spec_rel}"])
    if output is None:
        raise SpecUnavailable(f"{spec_rel} does not exist at {base_ref} (new spec: nothing to compare)")
    return output, f"{base_ref}:{spec_rel}"


def run(args: argparse.Namespace) -> int:
    """CLI handler for `api-diff`: compare the spec with a base ref/file and fail on breaking changes."""
    repo_root = resolve_repo_root(args.repo)
    spec_path = (repo_root / args.spec).resolve()
    if not is_within(spec_path, repo_root) or not spec_path.is_file():
        raise UsageError(f"--spec must be a file inside the repository: {args.spec}")
    spec_rel = spec_path.relative_to(repo_root).as_posix()
    if bool(args.base_ref) == bool(args.base_file):
        raise UsageError("give exactly one of --base-ref REF or --base-file PATH")
    details = {"spec": spec_rel, "base": args.base_file or f"{args.base_ref}:{spec_rel}"}
    try:
        base_text, base_label = _read_base(repo_root, spec_rel, args.base_ref, args.base_file)
        base = parse_spec(base_text, base_label)
        current = parse_spec(spec_path.read_text(encoding="utf-8"), spec_rel)
    except SpecUnavailable as error:
        result = CheckResult(check_id=args.check_id, tool="devskills.api-diff", execution_status=EXEC_NOT_RUN,
                             gate_result=GATE_BLOCKED, domain_result="spec_unavailable", summary=str(error), details=details)
        return emit_result(args, repo_root, result, [f"api-diff: blocked — {error}"])
    findings = diff_specs(base, current)
    breaking = sum(finding.severity == "high" for finding in findings)
    result = CheckResult(
        check_id=args.check_id, tool="devskills.api-diff", execution_status=EXEC_COMPLETED,
        gate_result=gate_from_findings(findings), domain_result=f"{breaking} breaking change(s)",
        summary=severity_summary(findings), findings=findings,
        details=details | {"paths_before": len(base.get("paths") or {}), "paths_after": len(current.get("paths") or {})},
        evidence_refs=[spec_rel])
    lines = [f"api-diff {details['base']} -> {spec_rel}: {breaking} breaking change(s)", *format_findings(findings)]
    if breaking:
        lines.append("  breaking changes need a new version/endpoint, a compatible default, or an approved waiver")
    return emit_result(args, repo_root, result, lines)
