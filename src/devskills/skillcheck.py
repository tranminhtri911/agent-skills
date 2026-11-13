"""Validate SKILL.md packages (Agent Skills specification + this project's rules).

Checks: frontmatter syntax and allowed keys, name format and directory match,
description length and trigger style, body length, relative links, and that
every `ds.py <command>` mentioned in the docs exists in the CLI (so the docs
cannot drift from the runtime).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from devskills.models import Finding

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PORTABLE_KEYS = frozenset({"name", "description", "license", "compatibility", "metadata", "allowed-tools"})
CLAUDE_ONLY_KEYS = frozenset({
    "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable", "disallowed-tools",
    "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
})
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# Matches `ds.py <command>` and the `DS <command>` shorthand used in SKILL.md files.
COMMAND_PATTERN = re.compile(r"(?:ds\.py\"?|\bDS)\s+([a-z][a-z-]+)")
MAX_BODY_LINES = 500
TARGET_BODY_LINES = 250


class FrontmatterError(ValueError):
    pass


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    """Parse the YAML subset used by skills: scalars, quoted strings, block scalars, one nested map.

    Returns (fields, body, body_start_line).
    """
    if not text.startswith("---\n"):
        raise FrontmatterError("SKILL.md must start with '---' frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise FrontmatterError("frontmatter is not closed with '---'")
    lines = text[4:end].split("\n")
    body = text[end + 5:]
    fields: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):(?:\s+(.*))?$", line)
        if not match:
            raise FrontmatterError(f"unsupported frontmatter line: {line!r}")
        key, raw_value = match.group(1), (match.group(2) or "").strip()
        if raw_value in ("|", ">", "|-", ">-", "|+", ">+"):
            block: list[str] = []
            while index < len(lines) and (lines[index].startswith(" ") or not lines[index].strip()):
                block.append(lines[index].strip())
                index += 1
            fields[key] = ("\n" if raw_value.startswith("|") else " ").join(part for part in block if part).strip()
        elif raw_value == "":
            nested: dict[str, str] = {}
            while index < len(lines) and lines[index].startswith("  "):
                nested_match = re.match(r"^\s+([\w.-]+):\s*(.*)$", lines[index])
                if not nested_match:
                    raise FrontmatterError(f"unsupported nested line: {lines[index]!r}")
                nested[nested_match.group(1)] = _scalar(nested_match.group(2))
                index += 1
            fields[key] = nested
        else:
            fields[key] = _scalar(raw_value)
    return fields, body, text[:end + 5].count("\n") + 1


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace('\\"', '"') if raw[0] == '"' else inner.replace("''", "'")
    if ": " in raw or raw.startswith(("[", "{", "&", "*", "!", "%", "@", "`")):
        raise FrontmatterError(f"value must be quoted: {raw[:60]!r}")
    return raw


def validate_skill(skill_dir: Path, known_commands: set[str]) -> list[Finding]:
    """Validate one skill folder: frontmatter, naming, description, body length, links, referenced commands."""
    findings: list[Finding] = []
    skill_file = skill_dir / "SKILL.md"
    location = str(skill_file)

    def add(rule_id: str, severity: str, message: str, line: int | None = None) -> None:
        findings.append(Finding(rule_id=rule_id, severity=severity, message=message, path=location, line=line))

    if not skill_file.is_file():
        add("SKILL-MISSING", "high", "SKILL.md not found")
        return findings
    text = skill_file.read_text(encoding="utf-8")
    try:
        fields, body, body_start = parse_frontmatter(text)
    except FrontmatterError as error:
        add("SKILL-FRONTMATTER", "high", str(error), 1)
        return findings

    name = fields.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name) or len(name) > 64:
        add("SKILL-NAME", "high", f"name {name!r} must be 1-64 lowercase letters, digits and single hyphens")
    elif name != skill_dir.name:
        add("SKILL-NAME-DIR", "high", f"name {name!r} must match the directory name {skill_dir.name!r}")
    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        add("SKILL-DESCRIPTION", "high", "description is required")
    else:
        if len(description) > 1024:
            add("SKILL-DESCRIPTION-LENGTH", "high", f"description has {len(description)} characters (max 1024)")
        elif len(description) > 600:
            add("SKILL-DESCRIPTION-LONG", "low", f"description has {len(description)} characters; long listings get truncated")
        if not description.startswith("Use when"):
            add("SKILL-DESCRIPTION-TRIGGER", "low", "description should start with 'Use when' and list triggers, not the workflow")
    compatibility = fields.get("compatibility")
    if compatibility is not None and (not isinstance(compatibility, str) or not 1 <= len(compatibility) <= 500):
        add("SKILL-COMPATIBILITY", "high", "compatibility must be 1-500 characters")
    metadata = fields.get("metadata")
    if metadata is not None and (not isinstance(metadata, dict) or not all(isinstance(value, str) for value in metadata.values())):
        add("SKILL-METADATA", "high", "metadata must map strings to strings")
    for key in fields:
        if key in CLAUDE_ONLY_KEYS:
            add("SKILL-NONPORTABLE-KEY", "low", f"`{key}` works in Claude Code only; other hosts reject it")
        elif key not in PORTABLE_KEYS:
            add("SKILL-UNKNOWN-KEY", "high", f"unknown frontmatter key `{key}`")

    body_lines = body.count("\n") + 1
    if body_lines > MAX_BODY_LINES:
        add("SKILL-BODY-LENGTH", "high", f"body has {body_lines} lines (max {MAX_BODY_LINES}); move detail to references/")
    elif body_lines > TARGET_BODY_LINES:
        add("SKILL-BODY-LONG", "low", f"body has {body_lines} lines (target ≤ {TARGET_BODY_LINES})")

    documents = [(skill_file, body, body_start)]
    documents += [(path, path.read_text(encoding="utf-8"), 1) for path in sorted((skill_dir / "references").glob("*.md"))]
    for document_path, document_text, first_line in documents:
        for line_offset, line in enumerate(document_text.splitlines()):
            line_number = first_line + line_offset
            for link in LINK_PATTERN.findall(line):
                if re.match(r"^(https?:|mailto:|#)", link):
                    continue
                target = (document_path.parent / link.split("#", 1)[0]).resolve()
                if not target.exists():
                    findings.append(Finding("SKILL-BROKEN-LINK", "high", f"link target not found: {link}", str(document_path), line_number))
                elif document_path == skill_file and len(Path(link).parts) > 2:
                    findings.append(Finding("SKILL-DEEP-LINK", "low", f"reference nested deeper than one level: {link}", str(document_path), line_number))
            for command in COMMAND_PATTERN.findall(line):
                if command not in known_commands:
                    findings.append(Finding("SKILL-UNKNOWN-COMMAND", "high", f"`ds.py {command}` is not a runtime command", str(document_path), line_number))
            if re.search(r"/Users/[^/\s]+/|/home/[^/\s]+/|C:\\\\Users\\\\", line):
                findings.append(Finding("SKILL-ABSOLUTE-PATH", "medium", "machine-specific absolute path", str(document_path), line_number))
    if "ds.py" in text and not (skill_dir / "scripts" / "ds.py").is_file():
        add("SKILL-SCRIPT-MISSING", "high", "SKILL.md references scripts/ds.py but the file is missing")
    return findings


def discover_skill_dirs(paths: list[str]) -> list[Path]:
    candidates = [Path(path) for path in paths] if paths else [Path.cwd()]
    skill_dirs: list[Path] = []
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            skill_dirs.append(candidate)
        elif candidate.is_dir():
            skill_dirs.extend(sorted(path.parent for path in candidate.glob("*/SKILL.md")))
    return skill_dirs


def run(args: argparse.Namespace) -> int:
    """CLI handler for `validate-skills`; exit 3 when any skill has a high-severity problem."""
    from devskills.cli import subcommand_names

    known_commands = subcommand_names()
    skill_dirs = discover_skill_dirs(args.paths)
    report: dict[str, list[dict[str, Any]]] = {}
    has_errors = False
    for skill_dir in skill_dirs:
        findings = validate_skill(skill_dir, known_commands)
        report[skill_dir.name] = [finding.to_dict() for finding in findings]
        has_errors = has_errors or any(finding.severity in ("high", "critical") for finding in findings)
    if args.json:
        print(json.dumps({"skills": report, "valid": not has_errors and bool(skill_dirs)}, indent=2, ensure_ascii=False))
    else:
        if not skill_dirs:
            print("no skills found (pass a skills directory or skill folders)")
        for skill_name, findings in report.items():
            status = "ok" if not any(item["severity"] in ("high", "critical") for item in findings) else "INVALID"
            print(f"{status:8} {skill_name}")
            for item in findings:
                location = f"{Path(item['path']).name}:{item.get('line', '')}"
                print(f"         [{item['severity']}] {item['rule_id']} {location} {item['message']}")
    return 0 if skill_dirs and not has_errors else 3
