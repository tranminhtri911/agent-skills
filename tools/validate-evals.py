#!/usr/bin/env python3
"""Validate offline behavioral scenario definitions; this does not execute an agent."""
import json
from pathlib import Path


def validate(path):
    """Return errors for malformed or duplicate scenario definitions."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seen, errors = set(), []
    for scenario in data["scenarios"]:
        identifier = scenario.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            errors.append(f"missing/duplicate scenario ID: {identifier}")
        seen.add(identifier)
        for key in ("skill", "task", "expect"):
            if not isinstance(scenario.get(key), str) or not scenario[key].strip():
                errors.append(f"{identifier}: missing {key}")
    return errors


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(Path(__file__).resolve().parents[1] / "evals/scenarios.json"))
    errors = validate(parser.parse_args().path)
    print("\n".join(errors) if errors else "Scenario definitions valid; agent behavior remains untested.")
    raise SystemExit(1 if errors else 0)
