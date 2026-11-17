"""Detect which code-style references apply to a repository, per project root, from the source itself.

A project root is the repository root or any directory holding a manifest (package.json, pyproject.toml,
pubspec.yaml, *.csproj …), so a monorepo with a Django API, a Next.js web app and a Flutter app gets
separate answers. Languages come from file extensions, frameworks from the manifests (reusing
`inventory.detect_stack`) plus a few markers it does not cover (Flutter, Android/Compose, SwiftUI,
ASP.NET Core web SDK), and style tools from the formatter/linter configs present. Nothing is executed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from devskills.fsutil import list_repo_files, read_text_limited, resolve_repo_root
from devskills.inventory import detect_stack

REPOSITORY_ROOT = "."
MAX_SWIFT_FILES_SCANNED = 40

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript", ".js": "typescript", ".jsx": "typescript",
    ".mjs": "typescript", ".cjs": "typescript", ".vue": "typescript",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".go": "go",
    ".swift": "swift",
    ".dart": "dart",
    ".sql": "sql",
}
# Build scripts are code but not the project's language of record for style purposes.
NON_SOURCE_NAMES = frozenset({"build.gradle.kts", "settings.gradle.kts"})

FRAMEWORK_BY_STACK_NAME = {
    "Django": "django", "Django REST framework": "django",
    "FastAPI": "fastapi",
    "React": "react", "Next.js": "react", "React Native": "react", "Expo": "react",
    "Vue": "vue", "Nuxt": "vue",
    "Angular": "angular",
    "NestJS": "nestjs",
    "Spring Boot (web)": "spring", "Spring WebFlux": "spring", "Spring Data JPA": "spring",
    "ASP.NET Core": "aspnet-core",
    "Laravel": "laravel",
}
# Which language reference each framework reference builds on (mirrors the code-style skill table).
FRAMEWORK_LANGUAGE = {
    "django": "python", "fastapi": "python",
    "react": "typescript", "vue": "typescript", "angular": "typescript", "nestjs": "typescript",
    "spring": "java", "android-compose": "kotlin", "aspnet-core": "csharp",
    "laravel": "php", "swiftui": "swift", "flutter": "dart",
}

MANIFEST_NAMES = frozenset({
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "manage.py", "composer.json", "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", "pubspec.yaml", "Package.swift", "Cargo.toml", "Gemfile",
})
MANIFEST_PATTERNS = (re.compile(r"requirements.*\.txt$"), re.compile(r".+\.csproj$"))

STYLE_TOOL_PATTERNS = (
    ".editorconfig", ".eslintrc*", "eslint.config.*", ".prettierrc*", "prettier.config.*", "biome.json*",
    "ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", "phpcs.xml*", "pint.json", ".php-cs-fixer*.php",
    ".golangci.y*ml", "detekt*.yml", ".swiftlint.yml", ".swift-format", "analysis_options.yaml",
    "checkstyle*.xml", "stylecop.json", ".clang-format", "rustfmt.toml", ".rubocop.yml", ".sqlfluff",
)
PYPROJECT_STYLE_SECTIONS = ("ruff", "black", "isort", "pylint")


def is_manifest(name: str) -> bool:
    return name in MANIFEST_NAMES or any(pattern.match(name) for pattern in MANIFEST_PATTERNS)


def parent_of(rel_path: str) -> str:
    parent = PurePosixPath(rel_path).parent.as_posix()
    return REPOSITORY_ROOT if parent in ("", ".") else parent


def root_of(rel_path: str, roots: list[str]) -> str:
    """The deepest project root containing the path; the repository root when none does."""
    containing_roots = [root for root in roots if root != REPOSITORY_ROOT and rel_path.startswith(root + "/")]
    if not containing_roots:
        return REPOSITORY_ROOT
    return max(containing_roots, key=len)


def language_of(rel_path: str) -> str | None:
    name = PurePosixPath(rel_path).name
    if name in NON_SOURCE_NAMES:
        return None
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(rel_path).suffix.lower())


def _frameworks_from_markers(repo_root: Path, root: str, root_files: list[str]) -> set[str]:
    """Frameworks that manifests alone do not reveal to `detect_stack`."""
    frameworks: set[str] = set()
    for rel_path in root_files:
        if parent_of(rel_path) != root:
            continue
        name = PurePosixPath(rel_path).name
        is_marker_file = name in ("pubspec.yaml", "build.gradle", "build.gradle.kts") or name.endswith(".csproj")
        if not is_marker_file:
            continue
        text = read_text_limited(repo_root / rel_path) or ""
        if name == "pubspec.yaml":
            if re.search(r"^\s*sdk:\s*flutter\b", text, re.MULTILINE):
                frameworks.add("flutter")
        elif name.endswith(".csproj"):
            if "Microsoft.NET.Sdk.Web" in text:
                frameworks.add("aspnet-core")
        elif re.search(r"com\.android\.(application|library)|androidx\.compose|compose\s*=\s*true", text):
            frameworks.add("android-compose")
    swift_files = [path for path in root_files if path.endswith(".swift")][:MAX_SWIFT_FILES_SCANNED]
    for rel_path in swift_files:
        if re.search(r"^\s*import\s+SwiftUI\b", read_text_limited(repo_root / rel_path, 64 * 1024) or "", re.MULTILINE):
            frameworks.add("swiftui")
            break
    return frameworks


def _style_tools(repo_root: Path, directory: str, files: list[str]) -> list[str]:
    tools = []
    for rel_path in files:
        if parent_of(rel_path) != directory:
            continue
        name = PurePosixPath(rel_path).name
        if any(PurePosixPath(name).match(pattern) for pattern in STYLE_TOOL_PATTERNS):
            tools.append(rel_path)
        elif name == "pyproject.toml":
            text = read_text_limited(repo_root / rel_path) or ""
            for section in PYPROJECT_STYLE_SECTIONS:
                if re.search(rf"^\[tool\.{section}(\.|\])", text, re.MULTILINE):
                    tools.append(f"{rel_path} [tool.{section}]")
    return sorted(tools)


def _references(languages: list[str], frameworks: list[str]) -> list[str]:
    """Language references first, each followed by the frameworks that build on it."""
    references = []
    for language in languages:
        references.append(f"language-{language}.md")
        references += [f"framework-{framework}.md" for framework in frameworks if FRAMEWORK_LANGUAGE[framework] == language]
    return references


def detect_style(repo_root: Path, files: list[str] | None = None) -> dict[str, Any]:
    """Per project root: languages by file count, frameworks, style tools and the code-style references to read."""
    if files is None:
        files, _truncated = list_repo_files(repo_root)
    roots = sorted({REPOSITORY_ROOT} | {parent_of(path) for path in files if is_manifest(PurePosixPath(path).name)})
    files_by_root: dict[str, list[str]] = {root: [] for root in roots}
    for rel_path in files:
        files_by_root[root_of(rel_path, roots)].append(rel_path)

    stack = detect_stack(repo_root, files)
    stack_frameworks: dict[str, set[str]] = {}
    for items in stack["by_category"].values():
        for item in items:
            framework = FRAMEWORK_BY_STACK_NAME.get(item["name"])
            if framework:
                stack_frameworks.setdefault(root_of(item["source"], roots), set()).add(framework)

    top_level_tools = _style_tools(repo_root, REPOSITORY_ROOT, files)
    result_roots = []
    for root in roots:
        root_files = files_by_root[root]
        counts: dict[str, int] = {}
        for rel_path in root_files:
            language = language_of(rel_path)
            if language:
                counts[language] = counts.get(language, 0) + 1
        frameworks = stack_frameworks.get(root, set()) | _frameworks_from_markers(repo_root, root, root_files)
        languages = sorted(counts, key=lambda language: (-counts[language], language))
        # A framework implies its language even before any source file exists (a fresh scaffold).
        for framework in sorted(frameworks):
            if FRAMEWORK_LANGUAGE[framework] not in languages:
                languages.append(FRAMEWORK_LANGUAGE[framework])
        if not languages and root != REPOSITORY_ROOT:
            continue
        own_tools = _style_tools(repo_root, root, root_files) if root != REPOSITORY_ROOT else []
        result_roots.append({
            "root": root,
            "languages": [{"language": language, "files": counts.get(language, 0)} for language in languages],
            "frameworks": sorted(frameworks),
            "style_tools": sorted(set(own_tools + top_level_tools)),
            "references": _references(languages, sorted(frameworks)),
        })
    return {"roots": result_roots}


def style_for_file(repo_root: Path, rel_path: str, detection: dict[str, Any] | None = None) -> dict[str, Any]:
    """The references for one file: its own language plus the frameworks of its project root that use it."""
    detection = detection if detection is not None else detect_style(repo_root)
    roots = [item["root"] for item in detection["roots"]]
    root = root_of(rel_path, roots)
    root_info = next((item for item in detection["roots"] if item["root"] == root), None)
    language = language_of(rel_path)
    frameworks = [framework for framework in (root_info or {}).get("frameworks", [])
                  if language and FRAMEWORK_LANGUAGE[framework] == language]
    return {
        "path": rel_path,
        "root": root,
        "language": language,
        "frameworks": frameworks,
        "style_tools": (root_info or {}).get("style_tools", []),
        "references": _references([language], frameworks) if language else [],
    }


def render_text(detection: dict[str, Any]) -> str:
    lines = ["Code-style references per project root (read them from the code-style skill's references/):"]
    for item in detection["roots"]:
        languages = ", ".join(f"{entry['language']} ({entry['files']})" for entry in item["languages"]) or "no source files"
        frameworks = f"; frameworks: {', '.join(item['frameworks'])}" if item["frameworks"] else ""
        lines.append(f"- {item['root']}: {languages}{frameworks}")
        if item["references"]:
            lines.append(f"    read: {', '.join(item['references'])}")
        if item["style_tools"]:
            lines.append(f"    repository style tools (they win): {', '.join(item['style_tools'])}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    """CLI handler for `style`: references for the whole repository, or for one file with --path."""
    repo_root = resolve_repo_root(args.repo)
    detection = detect_style(repo_root)
    if args.path:
        target = Path(args.path)
        target = target if target.is_absolute() else (Path.cwd() / target)
        try:
            rel_path = target.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            print(f"{target} is outside the repository {repo_root}")
            return 2
        result = dict(style_for_file(repo_root, rel_path, detection), repository=str(repo_root))
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"{rel_path}: {result['language'] or 'not source code'} in {result['root']}; read: "
                  f"{', '.join(result['references']) or '-'}")
        return 0
    print(json.dumps(detection, indent=2, ensure_ascii=False) if args.json else render_text(detection))
    return 0
