"""Offline OpenAPI sample validation; references never fetch files or URLs."""

from __future__ import annotations

import copy
import re
from typing import Any

from devskills.api_contract import SpecUnavailable

MAX_DEPTH = 32
ANNOTATIONS = {"title", "description", "default", "example", "examples", "deprecated", "xml", "externalDocs",
               "discriminator", "readOnly", "writeOnly"}
SCHEMA_KEYS = {"type", "enum", "const", "properties", "required", "additionalProperties", "items", "allOf", "anyOf",
               "oneOf", "not", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
               "minLength", "maxLength", "pattern", "format", "minItems", "maxItems", "uniqueItems",
               "minProperties", "maxProperties", "nullable"} | ANNOTATIONS


class SampleSchemas:
    """Resolve bounded local schemas and validate values with the optional jsonschema package."""

    def __init__(self, spec: dict[str, Any]):
        try:
            import jsonschema
        except ImportError as error:
            raise SpecUnavailable("api-examples needs the contracts extra (jsonschema); install .[contracts] with the lockfile") from error
        self.library = jsonschema
        self.spec = spec
        version = str(spec.get("openapi", ""))
        if not version.startswith(("3.0.", "3.1.")):
            raise SpecUnavailable("api-examples supports OpenAPI 3.0/3.1; other versions need a reviewed adapter")
        self.oas30 = version.startswith("3.0.")
        self._schema_steps = 0

    def resolve(self, node: Any, seen: frozenset[str] = frozenset()) -> Any:
        """Resolve Reference Objects, rejecting missing, recursive and external references."""
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen or len(seen) >= MAX_DEPTH:
            raise SpecUnavailable("unresolved, external or recursive OpenAPI reference; bundle a finite local contract")
        target: Any = self.spec
        for token in ref[2:].split("/"):
            key = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or key not in target:
                raise SpecUnavailable("OpenAPI reference target does not exist")
            target = target[key]
        return self.resolve(target, seen | {ref})

    def normalize(self, raw: Any, side: str, depth: int = 0, seen: frozenset[str] = frozenset()) -> Any:
        """Translate OpenAPI 3.0 nullable/bounds and directional read/write-only fields.

        Unsupported assertions block instead of disappearing into an empty schema.
        Recursive schemas are deliberately outside this bounded offline profile.
        """
        if depth == 0:
            self._schema_steps = 0
        self._schema_steps += 1
        if depth > MAX_DEPTH or self._schema_steps > 10000:
            raise SpecUnavailable("sample schema exceeds the depth limit")
        if isinstance(raw, bool) and not self.oas30:
            return raw
        if not isinstance(raw, dict):
            raise SpecUnavailable("expected a schema object")
        if "$ref" in raw:
            ref = raw["$ref"]
            if ref in seen:
                raise SpecUnavailable("recursive sample schema needs a reviewed adapter")
            resolved = self.normalize(self.resolve(raw), side, depth + 1, seen | {ref})
            siblings = {key: value for key, value in raw.items() if key != "$ref"}
            return {"allOf": [resolved, self.normalize(siblings, side, depth + 1, seen)]} if siblings and not self.oas30 else resolved
        unknown = {key for key in raw if key not in SCHEMA_KEYS and not key.startswith("x-")}
        if unknown:
            raise SpecUnavailable("unsupported sample-schema keyword(s): " + ", ".join(sorted(unknown)))
        pattern = raw.get("pattern")
        if isinstance(pattern, str) and (len(pattern) > 256 or re.search(r"[()|]|\\[1-9]", pattern)
                or len(re.findall(r"(?<!\\)[+*]|\{\d+,", pattern)) > 1):
            raise SpecUnavailable("complex regex needs a reviewed validator with execution limits")
        result = {key: copy.deepcopy(value) for key, value in raw.items()
                  if key not in ANNOTATIONS and key != "nullable" and not key.startswith("x-")}
        for keyword in ("allOf", "anyOf", "oneOf"):
            if keyword in result:
                if not isinstance(raw[keyword], list) or not raw[keyword]:
                    raise SpecUnavailable(f"invalid {keyword} schema")
                result[keyword] = [self.normalize(part, side, depth + 1, seen) for part in raw[keyword]]
        for keyword in ("not", "items", "additionalProperties"):
            if keyword in result and isinstance(result[keyword], (dict, bool)):
                result[keyword] = self.normalize(result[keyword], side, depth + 1, seen) if isinstance(result[keyword], dict) else result[keyword]
        if "properties" in raw:
            if not isinstance(raw["properties"], dict):
                raise SpecUnavailable("schema properties must be an object")
            result["properties"] = {}
            required = set(raw.get("required", []))
            for name, prop in raw["properties"].items():
                resolved = self.resolve(prop)
                forbidden = isinstance(resolved, dict) and resolved.get("readOnly" if side == "request" else "writeOnly") is True
                result["properties"][name] = False if forbidden else self.normalize(prop, side, depth + 1, seen)
                if forbidden:
                    required.discard(name)
            if "required" in raw:
                result["required"] = sorted(required)
        if self.oas30:
            for keyword, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
                if keyword in raw:
                    exclusive = raw[keyword]
                    if not isinstance(exclusive, bool):
                        raise SpecUnavailable("OpenAPI 3.0 exclusive bounds must be booleans")
                    result.pop(keyword, None)
                    if exclusive:
                        if bound not in raw:
                            raise SpecUnavailable("exclusive bound is missing its numeric limit")
                        result[keyword] = result.pop(bound)
            if raw.get("nullable") is True and "type" in raw:
                result["type"] = [raw["type"], "null"]
        elif "nullable" in raw:
            raise SpecUnavailable("OpenAPI 3.1 uses a null type, not nullable")
        return result

    def errors(self, value: Any, schema: Any, side: str) -> list[str]:
        """Return bounded assertion locations without echoing potentially sensitive values."""
        normalized = self.normalize(schema, side)
        validator = self.library.Draft202012Validator
        checker = self.library.FormatChecker()
        self._formats(normalized, checker)
        try:
            validator.check_schema(normalized)
        except self.library.SchemaError as error:
            raise SpecUnavailable("invalid OpenAPI sample schema") from error
        errors = []
        for error in validator(normalized, format_checker=checker).iter_errors(value):
            errors.append("/" + "/".join(str(part) for part in error.path) + f": {error.validator}")
            if len(errors) >= 20:
                break
        return errors

    def _formats(self, schema: Any, checker: Any) -> None:
        if not isinstance(schema, dict):
            return
        fmt = schema.get("format")
        if fmt in {"int32", "int64", "float", "double", "password"}:
            schema.pop("format")  # OpenAPI annotations; JSON type/declared bounds still apply.
        elif fmt and fmt not in checker.checkers:
            raise SpecUnavailable("sample format has no installed validator: " + str(fmt))
        for key in ("properties",):
            for child in (schema.get(key) or {}).values():
                self._formats(child, checker)
        for key in ("items", "additionalProperties", "not"):
            self._formats(schema.get(key), checker)
        for key in ("allOf", "anyOf", "oneOf"):
            for child in schema.get(key, []):
                self._formats(child, checker)

    def fields(self, schema: Any, prefix: str) -> dict[str, Any]:
        """Inventory nested request fields as JSON pointers, including containers and array items."""
        result: dict[str, Any] = {}

        def visit(node: Any, name: str, depth: int) -> None:
            if depth > MAX_DEPTH:
                raise SpecUnavailable("request field inventory exceeds the depth limit")
            if node is False:
                return
            result.setdefault(name, node)
            if not isinstance(node, dict):
                return
            for key, child in (node.get("properties") or {}).items():
                visit(child, name + "/" + key.replace("~", "~0").replace("/", "~1"), depth + 1)
            if "items" in node:
                visit(node["items"], name + "/*", depth + 1)
            for kind in ("allOf", "oneOf", "anyOf"):
                for child in node.get(kind, []):
                    visit(child, name, depth + 1)

        visit(self.normalize(schema, "request"), prefix, 0)
        return result
