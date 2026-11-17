"""Project profile (`.devskills.toml`) with safe defaults.

A repository may tune style checks and tighten rules, but it cannot widen
safety permissions (plan §25.1, SAFE-011): network allowances are accepted
only from the command line, never from files inside the code under test.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from devskills.models import SEVERITIES, UsageError

PROFILE_FILE_NAME = ".devskills.toml"

DEFAULT_PROFILE: dict[str, Any] = {
    "code": {
        # Follow existing comment conventions unless a project opts into a style check.
        "multiline_comment_style": "off",
        "max_function_lines": 60,
        "doc_min_lines": 12,
        "fail_on": "high",
        # Flag literals that repeat an existing enum/constant value (CODE-011).
        "hardcoded_values": True,
    },
    "database": {
        "engine": "auto",
        "foreign_key_policy": "allowed",
        "index_prefixes": ["idx_", "ix_"],
        "unique_index_prefixes": ["uq_", "ux_", "uniq_"],
    },
    "testing": {
        "timeout_seconds": 900,
        "max_output_bytes": 10 * 1024 * 1024,
    },
    "visual": {
        "pixel_threshold": 16,
        "max_diff_ratio": 0.001,
    },
    "change": {
        # Globs of code that must not change without the user's approval (CHG-003), e.g. ["app/Services/Billing/**"].
        "protected_paths": [],
        "stable_after_days": 365,
        "large_edit_lines": 80,
    },
    "integrations": {
        # Optional CodeGraph call graph: auto (use when installed and indexed) | on | off.
        "codegraph": "auto",
    },
}

_ALLOWED_CHOICES: dict[tuple[str, str], frozenset[str]] = {
    ("code", "multiline_comment_style"): frozenset({"block", "line", "off"}),
    ("code", "fail_on"): frozenset(SEVERITIES),
    ("database", "engine"): frozenset({"auto", "postgresql", "mysql", "sqlite", "sqlserver", "oracle", "generic"}),
    ("database", "foreign_key_policy"): frozenset({"discouraged", "forbidden", "allowed"}),
    ("integrations", "codegraph"): frozenset({"auto", "on", "off"}),
}

# Keys that would loosen safety if a repository could set them.
_FORBIDDEN_REPOSITORY_KEYS = frozenset({"allowed_hosts", "allow_hosts", "network", "allow_production"})


def load_profile(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    """Return (profile, warnings) merged over defaults.

    Unknown keys produce warnings instead of being silently dropped (plan §25.5);
    wrong types or invalid choices raise UsageError so a broken profile is visible.
    """
    profile = copy.deepcopy(DEFAULT_PROFILE)
    warnings: list[str] = []
    profile_path = repo_root / PROFILE_FILE_NAME
    if not profile_path.is_file():
        return profile, warnings
    try:
        loaded = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise UsageError(f"cannot parse {profile_path}: {error}") from error

    for section_name, section_values in loaded.items():
        if section_name == "schema_version":
            continue
        if section_name not in profile or not isinstance(section_values, dict):
            warnings.append(f"{PROFILE_FILE_NAME}: unknown section [{section_name}] ignored")
            continue
        for key, value in section_values.items():
            if key in _FORBIDDEN_REPOSITORY_KEYS:
                warnings.append(
                    f"{PROFILE_FILE_NAME}: [{section_name}].{key} ignored; network/production "
                    "permissions are only accepted from the command line"
                )
                continue
            if key not in profile[section_name]:
                warnings.append(f"{PROFILE_FILE_NAME}: unknown key [{section_name}].{key} ignored")
                continue
            profile[section_name][key] = _validated_value(section_name, key, value, profile[section_name][key])
    return profile, warnings


def _validated_value(section: str, key: str, value: Any, default: Any) -> Any:
    """Check that `value` has the default's type and, when restricted, an allowed choice."""
    expected_type = type(default)
    # bool is a subclass of int in Python; reject it explicitly for numeric settings.
    if isinstance(value, bool) and expected_type is not bool:
        raise UsageError(f"{PROFILE_FILE_NAME}: [{section}].{key} must be {expected_type.__name__}")
    if expected_type is float and isinstance(value, int):
        value = float(value)
    if not isinstance(value, expected_type):
        raise UsageError(f"{PROFILE_FILE_NAME}: [{section}].{key} must be {expected_type.__name__}")
    if isinstance(value, list) and not all(isinstance(item, str) for item in value):
        raise UsageError(f"{PROFILE_FILE_NAME}: [{section}].{key} must be a list of strings")
    choices = _ALLOWED_CHOICES.get((section, key))
    if choices is not None and value not in choices:
        raise UsageError(f"{PROFILE_FILE_NAME}: [{section}].{key} must be one of {sorted(choices)}")
    return value
