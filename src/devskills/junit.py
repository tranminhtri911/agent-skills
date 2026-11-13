"""JUnit XML report parsing for run-tests.

Counts are derived from <testcase> elements rather than suite attributes,
because some runners write inconsistent totals. Messages are truncated and
redacted before they enter evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from devskills.secrets_scan import redact_text

MAX_REPORT_BYTES = 50 * 1024 * 1024
MAX_LISTED_FAILURES = 50


@dataclass
class JUnitSummary:
    """Test counts and failure details aggregated from one or more JUnit XML files."""
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    files: list[str] = field(default_factory=list)
    failed_cases: list[dict[str, str]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    cases: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return self.tests - self.failures - self.errors - self.skipped

    def to_dict(self) -> dict:
        return {
            "tests": self.tests,
            "passed": self.passed,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "files": self.files,
            "failed_cases": self.failed_cases,
            "parse_errors": self.parse_errors,
            "cases": self.cases,
        }


def parse_junit_files(paths: list[Path]) -> JUnitSummary:
    """Aggregate several JUnit files; unparseable files are listed, never counted as passing."""
    summary = JUnitSummary()
    for path in paths:
        summary.files.append(str(path))
        try:
            if path.stat().st_size > MAX_REPORT_BYTES:
                summary.parse_errors.append(f"{path}: larger than {MAX_REPORT_BYTES} bytes")
                continue
            root = ElementTree.parse(path).getroot()
        except (OSError, ElementTree.ParseError) as error:
            summary.parse_errors.append(f"{path}: {error}")
            continue
        if root.tag not in ("testsuite", "testsuites"):
            summary.parse_errors.append(f"{path}: expected testsuite or testsuites, got {root.tag}")
            continue
        for case in root.iter("testcase"):
            summary.tests += 1
            outcome = None
            for child in case:
                if child.tag in ("failure", "error", "skipped"):
                    outcome = child
                    break
            # Keep every identity, including skipped cases. Totals or a truncated
            # failure list cannot prove that a particular test actually passed.
            summary.cases.append({
                "file": redact_text(case.get("file", "")),
                "classname": redact_text(case.get("classname", "")),
                "name": redact_text(case.get("name", "")),
                "outcome": outcome.tag if outcome is not None else "passed",
            })
            if outcome is None:
                continue
            if outcome.tag == "skipped":
                summary.skipped += 1
                continue
            if outcome.tag == "failure":
                summary.failures += 1
            else:
                summary.errors += 1
            if len(summary.failed_cases) < MAX_LISTED_FAILURES:
                message = (outcome.get("message") or outcome.text or "").strip().splitlines()
                summary.failed_cases.append({
                    "name": f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"),
                    "kind": outcome.tag,
                    "message": redact_text(message[0][:300]) if message else "",
                })
    return summary
