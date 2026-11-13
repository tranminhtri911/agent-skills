"""Existing enums, choices and constant groups, and literals that duplicate them (CODE-011).

A status/type/role written as a bare string ("pending") next to an existing
`OrderStatus.PENDING` drifts silently when the enum changes. This module:
- collects the value sets a project already defines, per language family:
  Python Enum/StrEnum/TextChoices/IntegerChoices and `*_CHOICES` tuples,
  TS/JS string enums and `const X = {...} as const` objects, PHP backed enums
  and class constants, C#/Java enums and string constants;
- flags string literals in other files of the same family that equal one of
  those values, when the line looks like it uses the domain value (comparison,
  `case`/`in`, or a name token of the value set on the same line).

Static text matching only: findings are review signals, the agent confirms.
"""

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from devskills.fsutil import is_lockfile, is_secret_file, list_repo_files, read_text_limited
from devskills.models import Finding

RULE_ID = "GEN-HARDCODED-DOMAIN-VALUE"
MAX_INDEX_FILES = 8000
MAX_INDEX_FILE_BYTES = 256 * 1024

FAMILY_BY_SUFFIX = {
    ".py": "python",
    ".ts": "js", ".tsx": "js", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".vue": "js", ".svelte": "js",
    ".php": "php",
    ".cs": "csharp",
    ".java": "jvm", ".kt": "jvm",
}
# Files whose job is to spell values out: migrations, seeds, fixtures, translations, tests, generated code.
_EXEMPT_PATH = re.compile(
    r"(^|/)(migrations?|seeders?|seeds?|fixtures?|factories|locales?|lang|i18n|translations?|generated|__generated__)(/|$)"
    r"|\.(g|generated|designer)\.\w+$|\.d\.ts$", re.IGNORECASE)
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|e2e|testing)(/|$)|(_test|\.test|\.spec)\.\w+$|(^|/)test_[^/]+$|(Test|Tests|Spec)\.\w+$|conftest\.py$")
# Values worth tracking look like identifiers/codes; labels with spaces belong to i18n, not to this rule.
_VALUE_SHAPE = re.compile(r"^[A-Za-z][\w.:-]{2,63}$")
_GENERIC_VALUES = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "true", "false", "none", "null", "undefined", "yes", "no",
    "id", "name", "type", "value", "key", "text", "string", "number", "boolean", "object", "array", "default", "all",
    "asc", "desc", "json", "html", "utf-8", "utf8", "click", "change", "submit", "input", "button", "left", "right",
    "top", "bottom", "center", "small", "medium", "large", "primary", "secondary", "self", "this", "data", "error",
})
_GENERIC_NAME_TOKENS = frozenset({"choices", "choice", "enum", "enums", "const", "consts", "constant", "constants",
                                  "values", "value", "list", "types", "options", "keys", "map", "all", "default"})

_PY_ENUM_CLASS = re.compile(
    r"(?m)^([ \t]*)class\s+(\w+)\s*\(([^)]*\b(?:Enum|StrEnum|IntEnum|Flag|IntFlag|TextChoices|IntegerChoices|Choices)\b[^)]*)\)\s*:")
_PY_MEMBER = re.compile(r"""^\s+([A-Z][A-Z0-9_]*)\s*(?::\s*\w+\s*)?=\s*(['"])([^'"\n]{1,64})\2""")
_PY_CHOICES = re.compile(r"(?m)^\s*([A-Z][A-Z0-9_]*CHOICES)\s*(?::[^=]+)?=\s*[\[(]")
_PY_CHOICE_PAIR = re.compile(r"""\(\s*(['"])([^'"\n]{1,64})\1\s*,""")
_UPPER_CONSTANT = re.compile(r"""(?m)^\s*(?:(?:export|public|protected|private|internal|static|final|readonly)\s+)*"""
                             r"""(?:const\s+(?:string\s+|String\s+)?|static\s+final\s+String\s+)?"""
                             r"""([A-Z][A-Z0-9]*_[A-Z0-9_]+)\s*(?::\s*\w+\s*)?=\s*(['"])([^'"\n]{1,64})\2\s*;?\s*$""")
_TS_ENUM = re.compile(r"\benum\s+(\w+)\s*\{")
_TS_ENUM_MEMBER = re.compile(r"""(\w+)\s*=\s*(['"`])([^'"`\n]{1,64})\2""")
_JS_CONST_OBJECT = re.compile(r"\bconst\s+([A-Z]\w*)\s*(?::[^=]+)?=\s*(?:Object\.freeze\(\s*)?\{")
_JS_OBJECT_ENTRY = re.compile(r"""^\s*['"]?(\w+)['"]?\s*:\s*(['"`])([^'"`\n]{1,64})\2\s*$""")
_PHP_ENUM = re.compile(r"\benum\s+(\w+)\s*:\s*(?:string|int)\s*(?:implements\s+[\w\\, ]+)?\{")
_PHP_CASE = re.compile(r"""\bcase\s+(\w+)\s*=\s*(['"])([^'"\n]{1,64})\2\s*;""")
_CLASS_NAME = re.compile(r"\b(?:class|interface|object)\s+(\w+)")
_CS_ENUM = re.compile(r"\benum\s+(?:class\s+)?(\w+)\s*(?::\s*\w+\s*)?\{")
_STRING_LITERAL = re.compile(r"""(['"`])([A-Za-z][\w.:-]{2,63})\1""")
# `x == "a"`, `case "a"`, and any item of `x in ("a", "b")` / `in ["a", "b"]`.
_COMPARISON_BEFORE = re.compile(r"(===?|!==?|<>|\bcase)\s*$|\bin\s*[\[(][^\])]*$")
_COMPARISON_AFTER = re.compile(r"^\s*(===?|!==?|<>)")
# Lines that define values (another enum member, a union type) rather than use them.
_DEFINITION_LINE = re.compile(r"^\s*(?:(?:export\s+)?type\s+\w+|\||(?:case\s+)?[A-Z][A-Za-z0-9_]*\s*(?::\s*\w+\s*)?[:=](?![=>]))")
# `row["payment"]`, `$data['status']`: a key/field name, not a domain value.
_SUBSCRIPT_BEFORE = re.compile(r"[\w)\]]\s*\[\s*$")


@dataclass
class DomainValueSet:
    """One enum/choices/constant group the project defines."""

    name: str
    family: str
    defined_in: str
    members: dict[str, str] = field(default_factory=dict)  # value -> member name
    # "keys": constants that only spell field/param names (USER_ID = "user_id"); listed, never flagged.
    kind: str = "values"

    def tokens(self) -> set[str]:
        """Lower-case name words that signal the domain on a line (`OrderStatus` -> order, status)."""
        words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", self.name)
        return {word.lower() for word in words if len(word) >= 4 and word.lower() not in _GENERIC_NAME_TOKENS}

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "family": self.family, "defined_in": self.defined_in,
                "values": [f"{member}={value}" for value, member in list(self.members.items())[:8]],
                "size": len(self.members)}


def is_test_or_generated(rel_path: str) -> bool:
    """Tests, migrations, seeds, fixtures, translations and generated files: they spell values out on purpose."""
    return bool(_EXEMPT_PATH.search(rel_path) or _TEST_PATH.search(rel_path))


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _block_after(text: str, open_brace: int) -> str:
    """Text between `{` at open_brace and its matching `}` (string contents are not special-cased)."""
    depth = 0
    for index in range(open_brace, min(len(text), open_brace + 20000)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1:index]
    return ""


def _python_sets(rel_path: str, text: str) -> list[DomainValueSet]:
    sets: list[DomainValueSet] = []
    lines = text.splitlines()
    for match in _PY_ENUM_CLASS.finditer(text):
        indent, name = len(match.group(1).expandtabs()), match.group(2)
        value_set = DomainValueSet(name, "python", f"{rel_path}:{_line_at(text, match.start())}")
        for line in lines[_line_at(text, match.end()):]:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            member = _PY_MEMBER.match(line)
            if member:
                value_set.members.setdefault(member.group(3), f"{name}.{member.group(1)}")
        sets.append(value_set)
    for match in _PY_CHOICES.finditer(text):
        end = text.find("\n\n", match.end())
        body = text[match.end(): end if end != -1 else len(text)]
        value_set = DomainValueSet(match.group(1), "python", f"{rel_path}:{_line_at(text, match.start())}")
        for pair in _PY_CHOICE_PAIR.finditer(body):
            value_set.members.setdefault(pair.group(2), f"{match.group(1)}[{pair.group(2)!r}]")
        sets.append(value_set)
    return sets


def _js_sets(rel_path: str, text: str) -> list[DomainValueSet]:
    sets: list[DomainValueSet] = []
    for match in _TS_ENUM.finditer(text):
        value_set = DomainValueSet(match.group(1), "js", f"{rel_path}:{_line_at(text, match.start())}")
        for member in _TS_ENUM_MEMBER.finditer(_block_after(text, match.end() - 1)):
            value_set.members.setdefault(member.group(3), f"{match.group(1)}.{member.group(1)}")
        sets.append(value_set)
    for match in _JS_CONST_OBJECT.finditer(text):
        body = _block_after(text, match.end() - 1)
        entries = [_JS_OBJECT_ENTRY.match(part) for part in re.split(r"[,\n]", body) if part.strip()]
        # Only flat objects whose every entry is a string literal: those are value sets, not config or components.
        if len(entries) >= 2 and all(entries):
            value_set = DomainValueSet(match.group(1), "js", f"{rel_path}:{_line_at(text, match.start())}")
            for entry in entries:
                value_set.members.setdefault(entry.group(3), f"{match.group(1)}.{entry.group(1)}")
            sets.append(value_set)
    return sets


def _php_sets(rel_path: str, text: str) -> list[DomainValueSet]:
    sets: list[DomainValueSet] = []
    for match in _PHP_ENUM.finditer(text):
        value_set = DomainValueSet(match.group(1), "php", f"{rel_path}:{_line_at(text, match.start())}")
        for case in _PHP_CASE.finditer(_block_after(text, match.end() - 1)):
            value_set.members.setdefault(case.group(3), f"{match.group(1)}::{case.group(1)}")
        sets.append(value_set)
    return sets


def _clr_sets(rel_path: str, text: str, family: str) -> list[DomainValueSet]:
    """C#/Java/Kotlin enums: member names are the values string comparisons use (`status.ToString() == "Paid"`)."""
    sets: list[DomainValueSet] = []
    for match in _CS_ENUM.finditer(text):
        value_set = DomainValueSet(match.group(1), family, f"{rel_path}:{_line_at(text, match.start())}")
        # Drop comments and attributes; Java enum bodies end their constants at the first `;`.
        body = re.sub(r"//[^\n]*|/\*.*?\*/|\[[^\]]*\]|@\w+(\([^)]*\))?", "", _block_after(text, match.end() - 1), flags=re.DOTALL)
        for part in body.split(";")[0].split(","):
            member = re.match(r"\s*([A-Z]\w*)", part)
            if member:
                value_set.members.setdefault(member.group(1), f"{match.group(1)}.{member.group(1)}")
        sets.append(value_set)
    return sets


def _constant_groups(rel_path: str, text: str, family: str) -> list[DomainValueSet]:
    """`STATUS_PENDING = "pending"` style constants, grouped by the first word of the name (STATUS_*)."""
    owner_match = _CLASS_NAME.search(text)
    owner = owner_match.group(1) if owner_match and family != "python" else ""
    separator = "::" if family == "php" else "."
    groups: dict[str, DomainValueSet] = {}
    for match in _UPPER_CONSTANT.finditer(text):
        prefix = match.group(1).split("_")[0]
        group_name = f"{owner}{separator}{prefix}_*" if owner else f"{prefix}_*"
        value_set = groups.setdefault(prefix, DomainValueSet(group_name, family, f"{rel_path}:{_line_at(text, match.start())}"))
        constant = f"{owner}{separator}{match.group(1)}" if owner else match.group(1)
        value_set.members.setdefault(match.group(3), constant)
    for value_set in groups.values():
        mirrored = sum(_normalized(member.rsplit(separator, 1)[-1]) == _normalized(value) for value, member in value_set.members.items())
        if mirrored * 2 > len(value_set.members):
            value_set.kind = "keys"
    return [value_set for value_set in groups.values() if len(value_set.members) >= 2]


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def collect_domain_values(texts: dict[str, str]) -> list[DomainValueSet]:
    """Value sets defined in the given files (tests, migrations, fixtures and translations are skipped)."""
    sets: list[DomainValueSet] = []
    for rel_path, text in texts.items():
        family = FAMILY_BY_SUFFIX.get(PurePosixPath(rel_path).suffix.lower())
        if not family or is_test_or_generated(rel_path):
            continue
        if family == "python":
            found = _python_sets(rel_path, text)
        elif family == "js":
            found = _js_sets(rel_path, text)
        elif family == "php":
            found = _php_sets(rel_path, text)
        else:
            found = _clr_sets(rel_path, text, family)
        found += _constant_groups(rel_path, text, family)
        for value_set in found:
            value_set.members = {value: member for value, member in value_set.members.items()
                                 if _VALUE_SHAPE.match(value) and value.lower() not in _GENERIC_VALUES}
            if len(value_set.members) >= 2:
                sets.append(value_set)
    return sets


def index_repository(repo_root: Path) -> list[DomainValueSet]:
    """Scan the repository's source files (bounded) for value sets; cheap keyword filter before parsing."""
    files, _ = list_repo_files(repo_root, MAX_INDEX_FILES)
    texts: dict[str, str] = {}
    for rel_path in files:
        if PurePosixPath(rel_path).suffix.lower() not in FAMILY_BY_SUFFIX or is_secret_file(rel_path) or is_lockfile(rel_path):
            continue
        text = read_text_limited(repo_root / rel_path, MAX_INDEX_FILE_BYTES)
        if text and re.search(r"\benum\b|Enum\b|Choices\b|CHOICES|\bconst\b|[A-Z]_[A-Z]", text):
            texts[rel_path] = text
    return collect_domain_values(texts)


def _strip_line_comment(line: str, family: str) -> str:
    """Drop a trailing `#`/`//` comment, ignoring markers inside quotes (best effort)."""
    marker = "#" if family == "python" else "//"
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote and line[index - 1] != "\\":
                quote = ""
        elif char in "'\"`":
            quote = char
        elif line.startswith(marker, index):
            return line[:index]
    return line


def _python_literals(text: str) -> list[tuple[int, int, int, str]] | None:
    """(line, start column, end column, value) of plain one-line string tokens; docstrings and f-strings are skipped.

    Returns None when the file does not tokenize, so the caller falls back to line matching.
    """
    literals: list[tuple[int, int, int, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.STRING or token.start[0] != token.end[0]:
                continue
            prefix = re.match(r"[A-Za-z]*", token.string).group(0).lower()
            body = token.string[len(prefix):]
            if "b" in prefix or "f" in prefix or body[:3] in ('"""', "'''"):
                continue
            literals.append((token.start[0], token.start[1], token.end[1], body[1:-1]))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    return literals


def _line_literals(text: str, family: str) -> list[tuple[int, int, int, str]]:
    """String literals per line for non-Python files, skipping comment lines and trailing comments."""
    literals: list[tuple[int, int, int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.lstrip().startswith(("#", "//", "/*", "*", "<!--")) or re.match(r"\s*(import|use|using|require)\b", raw_line):
            continue
        line = _strip_line_comment(raw_line, family)
        for literal in _STRING_LITERAL.finditer(line):
            if not (literal.group(1) == "`" and "${" in literal.group(2)):
                literals.append((line_number, literal.start(), literal.end(), literal.group(2)))
    return literals


def hardcoded_value_findings(rel_path: str, text: str, value_sets: list[DomainValueSet]) -> list[Finding]:
    """Literals in `rel_path` that repeat a value an existing enum/constant already names.

    A literal counts when it is compared (`==`, `case`, `in (...)`) or when a name word of the value set
    appears elsewhere on the line (`status` for OrderStatus), so free text and unrelated keys stay quiet.
    """
    family = FAMILY_BY_SUFFIX.get(PurePosixPath(rel_path).suffix.lower())
    if not family or is_test_or_generated(rel_path):
        return []
    by_value: dict[str, list[DomainValueSet]] = {}
    for value_set in value_sets:
        if value_set.family == family and value_set.kind == "values" and not value_set.defined_in.startswith(f"{rel_path}:"):
            for value in value_set.members:
                by_value.setdefault(value, []).append(value_set)
    if not by_value:
        return []
    literals = (_python_literals(text) if family == "python" else None)
    if literals is None:
        literals = _line_literals(text, family)
    lines = text.splitlines()
    findings: list[Finding] = []
    reported_lines: set[int] = set()
    for line_number, start, end, value in literals:
        candidates = by_value.get(value)
        if not candidates or line_number in reported_lines:
            continue
        line = _strip_line_comment(lines[line_number - 1], family)
        if _DEFINITION_LINE.match(line) or (_SUBSCRIPT_BEFORE.search(line[:start]) and line[end:].lstrip().startswith("]")):
            continue
        # Words inside the literal itself do not count: `"created_at"` must not relate itself to CREATED_*.
        context = (line[:start] + " " + line[end:]).lower()
        compared = bool(_COMPARISON_BEFORE.search(line[:start]) or _COMPARISON_AFTER.match(line[end:]))
        scored = sorted(((sum(token in context for token in value_set.tokens()), value_set) for value_set in candidates),
                        key=lambda item: -item[0])
        if not (compared or scored[0][0]):
            continue
        related, value_set = scored[0]
        member = value_set.members[value]
        others = f"; also {len(candidates) - 1} other value set(s)" if len(candidates) > 1 else ""
        # Compared but not tied to the set by name: likely, not certain (`payment_type === 'other'`).
        findings.append(Finding(
            rule_id=RULE_ID, severity="medium" if related else "low", path=rel_path, line=line_number,
            message=f"literal '{value}' {'repeats' if related else 'equals'} {member} ({value_set.defined_in}{others})",
            hint=f"use {member} instead of the literal (CODE-011); if the value set is wrong, fix it there"))
        reported_lines.add(line_number)
    return findings
