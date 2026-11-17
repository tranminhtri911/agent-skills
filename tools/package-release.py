#!/usr/bin/env python3
"""Build an offline source ZIP from an explicit allowlist; never include runtime state."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"agent-skills.py", "README.md", "INSTALL.md", "LICENSE", "pyproject.toml", "requirements-lock.txt", "CHANGELOG.md"}
TREES = {"skills", "src", "tools", "docs", "evals", "tests"}
EXCLUDED = {".git", ".devskills", ".knowledge", ".ruff_cache", "__pycache__", "__MACOSX", ".pytest_cache", "node_modules"}
SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".yaml", ".yml", ".sql", ".html", ".csv"}


def release_files(root):
    """Return source files, rejecting symlinks and files outside the release allowlist."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (not path.is_file() or path.is_symlink()
                or any(part in EXCLUDED or part.startswith(".") or part.endswith(".egg-info") for part in relative.parts)
                or any(parent.is_symlink() for parent in path.parents if parent != root.parent)):
            continue
        if relative.as_posix() in ROOT_FILES or (relative.parts[0] in TREES and path.suffix in SUFFIXES):
            yield path, relative.as_posix()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
        for path, name in release_files(ROOT):
            archive.write(path, name)
    print(f"Created {args.output}; run scan-secrets before distributing.")
