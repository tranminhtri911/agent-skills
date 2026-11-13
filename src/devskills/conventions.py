"""Project conventions to reuse before writing new code (CTX-009).

Lists what the repository already provides so new code extends it instead of
re-inventing it:
- base types: classes/mixins that other classes inherit, with where they are
  defined when the project owns them (BaseService, TimeStampedModel, ApiController);
- shared modules: common/core/shared/utils/hooks/services folders and their size;
- custom hooks / composables defined in the repo (useAuth, useApiQuery);
- frequent decorators (@transaction.atomic, @api_view, @permission_classes);
- reference modules: sibling folders of the feature, i.e. finished examples of
  the same kind of module to copy structure, naming and tests from;
- domain values: enums/choices/constant groups to use instead of literals (CODE-011);
- patterns in use: role suffixes in class/file names (Repository, Service, Action,
  FormRequest, selectors.py…) and pattern libraries/tools in manifests and configs,
  so new code follows the source's own architecture instead of a textbook one.

Everything is static text matching; the agent confirms by reading the code.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from devskills.domain_values import collect_domain_values, is_test_or_generated

MAX_ITEMS = 15
_PY_CLASS = re.compile(r"(?m)^\s*class\s+(\w+)\s*\(([^)]*)\)\s*:")
_EXTENDS_CLASS = re.compile(r"\bclass\s+(\w+)(?:\s*<[^>{]*>)?\s+extends\s+([\w.\\]+)")
_CSHARP_CLASS = re.compile(r"\bclass\s+(\w+)(?:<[^>]*>)?\s*:\s*([\w.]+)")
_ANY_CLASS = re.compile(r"\b(?:class|interface|trait)\s+(\w+)")
_HOOK_DEFINITION = re.compile(r"\b(?:export\s+)?(?:function\s+|const\s+)(use[A-Z]\w*)")
_DECORATOR = re.compile(r"(?m)^\s*@([A-Za-z_][\w.]*)")
_IGNORED_BASES = frozenset({"object", "Exception", "Enum", "TypedDict", "NamedTuple", "Protocol", "Generic", "ABC"})
_IGNORED_DECORATORS = frozenset({"property", "staticmethod", "classmethod", "dataclass", "override", "abstractmethod",
                                 "pytest.fixture", "pytest.mark.parametrize", "functools.wraps", "wraps", "cached_property"})
SHARED_DIR = re.compile(
    r"(^|/)(common|core|shared|utils?|helpers?|libs?|base|foundation|hooks|composables|mixins|middlewares?|"
    r"exceptions|constants|services|api|clients?|components/(?:ui|common|shared))(/|$)", re.IGNORECASE)
_CODE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".php", ".cs", ".java", ".kt", ".go", ".rb"})
# Architectural roles recognised by class-name suffix; framework staples (Controller, Model, View) are left out.
_ROLE_SUFFIXES = ("Repository", "Repo", "Service", "UseCase", "Action", "Handler", "Command", "Query", "Factory", "Builder",
                  "Policy", "Request", "Resource", "Serializer", "Dto", "DTO", "Mapper", "Presenter", "ViewModel", "VM",
                  "Store", "Event", "Listener", "Observer", "Job", "Task", "Middleware", "Adapter", "Gateway", "Client",
                  "Provider", "Strategy", "State", "Specification", "Validator", "Selector")
# Python modules named after a role (Django styleguide `services.py`/`selectors.py`, `use_cases.py`...).
_ROLE_MODULES = {"services": "services.py", "service": "services.py", "selectors": "selectors.py", "repositories": "repositories.py",
                 "repository": "repositories.py", "use_cases": "use_cases.py", "usecases": "use_cases.py", "handlers": "handlers.py",
                 "commands": "commands.py", "queries": "queries.py", "policies": "policies.py", "serializers": "serializers.py",
                 "schemas": "schemas.py", "dtos": "dtos.py", "mappers": "mappers.py", "signals": "signals.py", "tasks": "tasks.py",
                 "adapters": "adapters.py", "gateways": "gateways.py", "clients": "clients.py", "validators": "validators.py"}
_PATTERN_LIBRARIES = {
    "django-fsm": "state machine", "django-fsm-2": "state machine", "viewflow": "state machine",
    "spatie/laravel-model-states": "state machine", "xstate": "state machine",
    "import-linter": "layer rules", "qossmic/deptrac": "layer rules", "deptrac/deptrac": "layer rules",
    "dependency-cruiser": "layer rules", "eslint-plugin-boundaries": "layer rules", "NetArchTest.Rules": "layer rules",
    "jscpd": "duplication check", "sebastian/phpcpd": "duplication check",
    "dependency-injector": "DI container", "inversify": "DI container", "tsyringe": "DI container",
    "factory-boy": "test data factories", "factory_boy": "test data factories", "fishery": "test data factories",
    "@reduxjs/toolkit": "client store", "redux": "client store", "zustand": "client store", "pinia": "client store",
    "@tanstack/react-query": "server-state cache", "swr": "server-state cache",
    "spatie/laravel-data": "DTO", "spatie/laravel-event-sourcing": "event sourcing",
}
_MANIFEST = re.compile(r"(^|/)(package\.json|composer\.json|requirements[^/]*\.txt|pyproject\.toml|Pipfile|[^/]+\.csproj|packages\.config)$")
_PATTERN_CONFIGS = {".importlinter": "layer rules", "deptrac.yaml": "layer rules", "deptrac.yml": "layer rules",
                    ".dependency-cruiser.js": "layer rules", ".dependency-cruiser.cjs": "layer rules",
                    ".dependency-cruiser.json": "layer rules", ".jscpd.json": "duplication check"}


def _bases(rel_path: str, text: str) -> list[tuple[str, str]]:
    """(class, base) pairs for the language of the file."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    pairs: list[tuple[str, str]] = []
    if suffix == ".py":
        for name, raw_bases in _PY_CLASS.findall(text):
            for base in raw_bases.split(","):
                base = base.strip().split("[")[0]
                if base and "=" not in base:
                    pairs.append((name, base))
    elif suffix == ".cs":
        pairs = _CSHARP_CLASS.findall(text)
    else:
        pairs = _EXTENDS_CLASS.findall(text)
    return [(name, base.rsplit("\\", 1)[-1]) for name, base in pairs if base.split(".")[-1] not in _IGNORED_BASES]


def detect_conventions(cached_texts: dict[str, str], feature_paths: list[str],
                       pattern: re.Pattern[str] | None = None) -> dict[str, Any]:
    """Summarize reusable project building blocks from already-read file texts."""
    code_texts = {path: text for path, text in cached_texts.items() if PurePosixPath(path).suffix.lower() in _CODE_SUFFIXES}
    defined_at: dict[str, str] = {}
    base_users: dict[str, list[str]] = {}
    hooks: dict[str, str] = {}
    decorators: Counter[str] = Counter()
    for path, text in code_texts.items():
        for match in _ANY_CLASS.finditer(text):
            defined_at.setdefault(match.group(1), f"{path}:{text.count(chr(10), 0, match.start()) + 1}")
        for name, base in _bases(path, text):
            base_users.setdefault(base, []).append(f"{name} ({path})")
        if PurePosixPath(path).suffix.lower() in (".ts", ".tsx", ".js", ".jsx", ".vue"):
            for match in _HOOK_DEFINITION.finditer(text):
                hooks.setdefault(match.group(1), path)
        if path.endswith(".py"):
            decorators.update(name for name in _DECORATOR.findall(text) if name not in _IGNORED_DECORATORS)

    base_types = []
    for base, users in sorted(base_users.items(), key=lambda item: -len(item[1])):
        short_name = base.split(".")[-1]
        # `models.Model` / `migrations.Migration` are framework bases even when a subclass reuses the short name.
        owned = None if "." in base or all(user.split(" ")[0] == short_name for user in users) else defined_at.get(short_name)
        if len(users) < 2 and not owned:
            continue
        base_types.append({"name": base, "subclasses": len(users), "defined_in": owned, "examples": users[:3]})
    # Project-owned bases first: they carry the house rules (auth, tenant scope, audit, errors).
    base_types.sort(key=lambda item: (item["defined_in"] is None, -item["subclasses"]))

    shared: Counter[str] = Counter()
    for path in cached_texts:
        match = SHARED_DIR.search(path)
        if match:
            shared[path[:match.end(2)]] += 1
    hook_uses = {name: sum(len(re.findall(rf"\b{name}\(", text)) for text in code_texts.values()) for name in hooks}

    return {
        "base_types": base_types[:MAX_ITEMS],
        "shared_modules": [{"path": path, "files": count} for path, count in shared.most_common(MAX_ITEMS)],
        "custom_hooks": [{"name": name, "defined_in": hooks[name], "uses": uses}
                         for name, uses in sorted(hook_uses.items(), key=lambda item: -item[1])[:MAX_ITEMS]],
        "frequent_decorators": [{"name": name, "uses": count} for name, count in decorators.most_common(MAX_ITEMS) if count >= 2],
        "reference_modules": reference_modules(list(cached_texts), feature_paths, pattern),
        "domain_values": _domain_values(cached_texts, pattern),
        "patterns_in_use": patterns_in_use(code_texts),
        "pattern_tools": pattern_tools(cached_texts),
    }


def patterns_in_use(code_texts: dict[str, str]) -> list[dict[str, Any]]:
    """Architectural roles the source already uses: {role, count, where (top folders), examples}."""
    found: dict[str, list[tuple[str, str]]] = {}
    for path, text in code_texts.items():
        if is_test_or_generated(path):
            continue
        for match in _ANY_CLASS.finditer(text):
            name = match.group(1)
            role = next((suffix for suffix in _ROLE_SUFFIXES if name.endswith(suffix) and len(name) > len(suffix)), None)
            if role:
                found.setdefault(role, []).append((name, path))
        module_role = _ROLE_MODULES.get(PurePosixPath(path).stem) if path.endswith(".py") else None
        if module_role:
            found.setdefault(module_role, []).append((path, path))
    roles = []
    for role, items in found.items():
        unique = list(dict.fromkeys(items))
        if len(unique) < 2:
            continue
        folders = Counter(str(PurePosixPath(path).parent) for _, path in unique)
        roles.append({"role": role, "count": len(unique), "where": [folder for folder, _ in folders.most_common(2)],
                      "examples": [name for name, _ in unique[:2]]})
    return sorted(roles, key=lambda item: -item["count"])[:MAX_ITEMS]


def pattern_tools(cached_texts: dict[str, str]) -> list[dict[str, str]]:
    """State-machine, layer-rule, duplication, DI and store libraries/configs the project already has."""
    tools: dict[str, dict[str, str]] = {}
    for path, text in cached_texts.items():
        config_kind = _PATTERN_CONFIGS.get(PurePosixPath(path).name)
        if config_kind:
            tools.setdefault(path, {"name": path, "kind": config_kind, "source": path})
        if not _MANIFEST.search(path):
            continue
        for library, kind in _PATTERN_LIBRARIES.items():
            if re.search(rf"(^|[\"'\s]){re.escape(library)}([\"'\s=<>~!^\[;,]|$)", text, re.MULTILINE):
                tools.setdefault(library, {"name": library, "kind": kind, "source": path})
    return list(tools.values())


def _domain_values(cached_texts: dict[str, str], pattern: re.Pattern[str] | None) -> list[dict[str, Any]]:
    """Enums/constant groups, the feature's own first (OrderStatus for an orders task), then the largest."""
    value_sets = collect_domain_values(cached_texts)
    value_sets.sort(key=lambda item: (not (pattern and (pattern.search(item.name) or pattern.search(item.defined_in))),
                                      item.kind != "values", -len(item.members)))
    return [item.to_dict() for item in value_sets[:MAX_ITEMS]]


def _kind_suffix(file_name: str) -> str:
    """`OrderController.php` -> `Controller.php`, `order_service.py` -> `service.py`, `OrderList.tsx` -> `List.tsx`."""
    stem, dot, extension = file_name.partition(".")
    tokens = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", stem)
    return f"{tokens[-1]}{dot}{extension}" if len(tokens) > 1 else ""


def reference_modules(all_paths: list[str], feature_paths: list[str],
                      pattern: re.Pattern[str] | None) -> list[dict[str, Any]]:
    """Finished modules of the same kind as the feature, to imitate.

    Layered repos: sibling files with the same kind suffix in the same folder
    (OrderController.php -> InvoiceController.php). Feature-folder repos: sibling
    folders of a folder named after the feature (apps/orders -> apps/invoices).
    """
    by_dir: dict[str, list[str]] = {}
    for path in all_paths:
        by_dir.setdefault(str(PurePosixPath(path).parent), []).append(path)
    references: dict[str, dict[str, Any]] = {}
    for feature_path in feature_paths[:20]:
        directory, name = str(PurePosixPath(feature_path).parent), PurePosixPath(feature_path).name
        suffix = _kind_suffix(name)
        if suffix:
            siblings = [path for path in by_dir.get(directory, [])
                        if path.endswith(suffix) and path != feature_path and not (pattern and pattern.search(path))]
            for path in siblings[:2]:
                references.setdefault(path, {"path": path, "kind": "file", "like": feature_path})
        if pattern and pattern.search(PurePosixPath(directory).name) and "/" in directory:
            parent = str(PurePosixPath(directory).parent)
            sibling_dirs = Counter(path[len(parent) + 1:].split("/")[0] for path in all_paths
                                   if path.startswith(parent + "/") and not path.startswith(directory + "/")
                                   and path.count("/") > parent.count("/") + 1)
            for sibling, count in sibling_dirs.most_common(2):
                if count >= 2 and not pattern.search(sibling):
                    references.setdefault(f"{parent}/{sibling}", {"path": f"{parent}/{sibling}", "kind": "folder", "like": directory})
    return list(references.values())[:8]


def render_conventions(conventions: dict[str, Any]) -> list[str]:
    """Markdown lines for the context map."""
    lines = ["", "## Project conventions to reuse (read before writing new code)", ""]
    for item in conventions.get("base_types", [])[:10]:
        owner = f" — defined in {item['defined_in']}" if item.get("defined_in") else " (framework/library)"
        lines.append(f"- base `{item['name']}`: {item['subclasses']} subclass(es){owner}; e.g. {', '.join(item['examples'][:2])}")
    if conventions.get("shared_modules"):
        lines.append("- shared modules: " + ", ".join(f"{item['path']} ({item['files']})" for item in conventions["shared_modules"][:8]))
    if conventions.get("custom_hooks"):
        lines.append("- custom hooks: " + ", ".join(f"{item['name']} ×{item['uses']}" for item in conventions["custom_hooks"][:8]))
    if conventions.get("frequent_decorators"):
        lines.append("- decorators: " + ", ".join(f"@{item['name']} ×{item['uses']}" for item in conventions["frequent_decorators"][:8]))
    if conventions.get("patterns_in_use"):
        lines.append("- patterns in use: " + ", ".join(
            f"{item['role']} ×{item['count']} ({', '.join(item['where'])})" for item in conventions["patterns_in_use"][:10]))
    if conventions.get("pattern_tools"):
        lines.append("- pattern libraries/tools: " + ", ".join(
            f"{item['name']} ({item['kind']})" for item in conventions["pattern_tools"][:10]))
    for item in conventions.get("domain_values", [])[:10]:
        label = "key constants" if item["kind"] == "keys" else "values"
        lines.append(f"- {label} `{item['name']}` ({item['defined_in']}): {', '.join(item['values'][:5])}"
                     f"{' …' if item['size'] > 5 else ''} — use these, never the bare literal")
    for item in conventions.get("reference_modules", []):
        lines.append(f"- reference {item['kind']} `{item['path']}` (same kind as {item['like']}): imitate layout, naming, tests")
    if len(lines) == 3:
        lines.append("- nothing detected statically; read the closest existing module by hand")
    return lines
