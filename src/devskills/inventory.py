"""Repository inventory and feature context map (discover-codebase skill, plan §7).

The tool collects facts that can be found mechanically: stack and versions
from manifests, repository instructions, test commands, files and symbols that
belong to a feature, their callers, and database entities. It never imports
application modules (CTX-006) and never reads secret files (AGENT-003).
Semantic understanding (invariants, transaction boundaries, unknowns) stays
with the agent, which fills `agent_must_fill` after reading the entry points.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from devskills import SCHEMA_VERSION
from devskills.codegraph import CodeGraph, affected_tests, detect, explore, index_status, resolve_mode
from devskills.conventions import detect_conventions, render_conventions
from devskills.fsutil import (
    atomic_write_json,
    atomic_write_text,
    ensure_state_dir,
    git_snapshot,
    is_lockfile,
    is_secret_file,
    list_repo_files,
    read_text_limited,
    resolve_repo_root,
    select_target_files,
    utc_now_iso,
)
from devskills.models import EXEC_COMPLETED, GATE_PASS, GATE_WARN, CheckResult
from devskills.output import emit_result
from devskills.profile import load_profile
from devskills.runs import artifacts_dir

# Budgets keep discovery bounded on large repositories (CTX-007).
MAX_FILE_BYTES = 512 * 1024
MAX_CACHED_BYTES = 64 * 1024 * 1024
MAX_FEATURE_FILES = 60
MAX_SYMBOLS = 60
MAX_CALLERS_PER_SYMBOL = 8
SAMPLE_LINES_PER_FILE = 3

INSTRUCTION_FILES = (
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".github/copilot-instructions.md", ".cursorrules",
    "README.md", "README.rst", "CONTRIBUTING.md", "ARCHITECTURE.md", "docs/architecture.md",
    ".editorconfig",
)
LINT_CONFIG_PATTERNS = (
    ".eslintrc*", "eslint.config.*", ".prettierrc*", "prettier.config.*", "biome.json", "ruff.toml", ".ruff.toml",
    "setup.cfg", "tox.ini", ".flake8", "mypy.ini", "pyrightconfig.json", "tsconfig.json", "phpcs.xml*",
    "phpstan.neon*", "pint.json", ".rubocop.yml", "checkstyle*.xml", ".golangci.y*ml", "rustfmt.toml", ".stylelintrc*",
)

NPM_PACKAGES = {
    "react": ("frontend", "React"), "next": ("frontend", "Next.js"), "vue": ("frontend", "Vue"),
    "nuxt": ("frontend", "Nuxt"), "@angular/core": ("frontend", "Angular"), "svelte": ("frontend", "Svelte"),
    "@sveltejs/kit": ("frontend", "SvelteKit"), "solid-js": ("frontend", "Solid"), "react-native": ("frontend", "React Native"),
    "expo": ("frontend", "Expo"), "express": ("backend", "Express"), "@nestjs/core": ("backend", "NestJS"),
    "fastify": ("backend", "Fastify"), "koa": ("backend", "Koa"), "hono": ("backend", "Hono"), "@hapi/hapi": ("backend", "hapi"),
    "prisma": ("database", "Prisma"), "@prisma/client": ("database", "Prisma Client"), "typeorm": ("database", "TypeORM"),
    "sequelize": ("database", "Sequelize"), "drizzle-orm": ("database", "Drizzle ORM"), "mongoose": ("database", "Mongoose"),
    "knex": ("database", "Knex"), "pg": ("database", "node-postgres"), "mysql2": ("database", "mysql2"),
    "ioredis": ("database", "ioredis"), "redis": ("database", "node-redis"), "bullmq": ("jobs", "BullMQ"), "bull": ("jobs", "Bull"),
    "jest": ("testing", "Jest"), "vitest": ("testing", "Vitest"), "@playwright/test": ("testing", "Playwright Test"),
    "cypress": ("testing", "Cypress"), "mocha": ("testing", "Mocha"), "@testing-library/react": ("testing", "Testing Library"),
    "@reduxjs/toolkit": ("state", "Redux Toolkit"), "redux": ("state", "Redux"), "zustand": ("state", "Zustand"),
    "pinia": ("state", "Pinia"), "vuex": ("state", "Vuex"), "@tanstack/react-query": ("state", "TanStack Query"),
    "swr": ("state", "SWR"), "typescript": ("tooling", "TypeScript"), "eslint": ("tooling", "ESLint"),
    "prettier": ("tooling", "Prettier"), "vite": ("tooling", "Vite"),
}
PYTHON_PACKAGES = {
    "fastapi": ("backend", "FastAPI"), "django": ("backend", "Django"), "djangorestframework": ("backend", "Django REST framework"),
    "flask": ("backend", "Flask"), "starlette": ("backend", "Starlette"), "litestar": ("backend", "Litestar"),
    "aiohttp": ("backend", "aiohttp"), "sqlalchemy": ("database", "SQLAlchemy"), "alembic": ("database", "Alembic"),
    "sqlmodel": ("database", "SQLModel"), "psycopg": ("database", "psycopg 3"), "psycopg2": ("database", "psycopg2"),
    "psycopg2-binary": ("database", "psycopg2"), "asyncpg": ("database", "asyncpg"), "pymysql": ("database", "PyMySQL"),
    "mysqlclient": ("database", "mysqlclient"), "redis": ("database", "redis-py"), "pymongo": ("database", "PyMongo"),
    "celery": ("jobs", "Celery"), "rq": ("jobs", "RQ"), "dramatiq": ("jobs", "Dramatiq"), "arq": ("jobs", "arq"),
    "apscheduler": ("jobs", "APScheduler"), "pydantic": ("tooling", "Pydantic"), "pytest": ("testing", "pytest"),
    "pytest-asyncio": ("testing", "pytest-asyncio"), "hypothesis": ("testing", "Hypothesis"),
    "playwright": ("testing", "Playwright (Python)"), "pytest-playwright": ("testing", "pytest-playwright"),
    "ruff": ("tooling", "Ruff"), "mypy": ("tooling", "mypy"),
}
COMPOSER_PACKAGES = {
    "laravel/framework": ("backend", "Laravel"), "symfony/framework-bundle": ("backend", "Symfony"),
    "slim/slim": ("backend", "Slim"), "doctrine/orm": ("database", "Doctrine ORM"), "phpunit/phpunit": ("testing", "PHPUnit"),
    "pestphp/pest": ("testing", "Pest"), "laravel/horizon": ("jobs", "Laravel Horizon"),
}
GO_MODULES = {
    "github.com/gin-gonic/gin": ("backend", "Gin"), "github.com/labstack/echo": ("backend", "Echo"),
    "github.com/gofiber/fiber": ("backend", "Fiber"), "github.com/go-chi/chi": ("backend", "chi"),
    "gorm.io/gorm": ("database", "GORM"), "github.com/jackc/pgx": ("database", "pgx"), "github.com/jmoiron/sqlx": ("database", "sqlx"),
}
JVM_ARTIFACTS = {
    "spring-boot-starter-web": ("backend", "Spring Boot (web)"), "spring-boot-starter-webflux": ("backend", "Spring WebFlux"),
    "spring-boot-starter-data-jpa": ("database", "Spring Data JPA"), "hibernate-core": ("database", "Hibernate"),
    "mybatis": ("database", "MyBatis"), "flyway-core": ("database", "Flyway"), "liquibase-core": ("database", "Liquibase"),
    "junit-jupiter": ("testing", "JUnit 5"), "ktor-server-core": ("backend", "Ktor"),
}
NUGET_PREFIXES = {
    "Microsoft.AspNetCore": ("backend", "ASP.NET Core"), "Microsoft.EntityFrameworkCore": ("database", "EF Core"),
    "Dapper": ("database", "Dapper"), "xunit": ("testing", "xUnit"), "NUnit": ("testing", "NUnit"),
    "MSTest": ("testing", "MSTest"), "Hangfire": ("jobs", "Hangfire"),
}
RUBY_GEMS = {
    "rails": ("backend", "Rails"), "sinatra": ("backend", "Sinatra"), "rspec-rails": ("testing", "RSpec"),
    "rspec": ("testing", "RSpec"), "sidekiq": ("jobs", "Sidekiq"), "pg": ("database", "pg"), "mysql2": ("database", "mysql2"),
}
DB_IMAGE_PATTERN = re.compile(
    r"image:\s*['\"]?(?:[\w./-]*/)?(postgres|postgis|mysql|mariadb|mongo|redis|rabbitmq|mssql/server|"
    r"mcr\.microsoft\.com/mssql|elasticsearch|opensearch|kafka|cassandra|clickhouse)[\w./-]*(?::([\w.-]+))?",
    re.IGNORECASE,
)

ROLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("test", re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|testing)(/|$)|(_test|\.test|\.spec|Tests?)\.\w+$|(^|/)test_[^/]+$|conftest\.py$")),
    ("migration", re.compile(r"(^|/)(migrations?|alembic/versions|db/migrate|database/migrations|flyway|liquibase)(/|$)|\.sql$", re.IGNORECASE)),
    ("route", re.compile(r"(router|routes|controller|endpoints?|handlers?|views\.py|urls\.py|resolvers?|api\.\w+$)", re.IGNORECASE)),
    ("service", re.compile(r"(services?|usecases?|use_cases?|interactors?|application)[/._]", re.IGNORECASE)),
    ("repository", re.compile(r"(repositor(y|ies)|repos?[/._]|daos?[/._]|crud[/._]|queries?[/._])", re.IGNORECASE)),
    ("model", re.compile(r"(models?|entit(y|ies)|schemas?|dtos?|types?)[/._]|schema\.prisma$", re.IGNORECASE)),
    ("job", re.compile(r"(jobs?|workers?|tasks?|batch|cron|queues?|consumers?|listeners?)[/._]", re.IGNORECASE)),
    ("screen", re.compile(r"(^|/)(pages?|screens?|views?|routes?|app)/.*\.(tsx|jsx|vue|svelte|html|blade\.php)$|page\.(tsx|jsx)$", re.IGNORECASE)),
    ("component", re.compile(r"(^|/)components?/|\.(vue|svelte|tsx|jsx)$", re.IGNORECASE)),
    ("state", re.compile(r"(^|/)(hooks?|stores?|state|slices?|composables)/|(^|/)use[A-Z]\w*\.(ts|js|tsx|jsx)$")),
    ("config", re.compile(r"(config|settings|\.env\.example|docker-compose|compose\.ya?ml|\.ya?ml$|\.toml$|\.ini$)", re.IGNORECASE)),
)
ROLE_READING_ORDER = ("route", "screen", "service", "repository", "model", "job", "state", "component", "migration", "config", "test", "other")

DB_ENTITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sql", re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(?:\w+[`\"\]]?\.[`\"\[]?)?(\w+)", re.IGNORECASE)),
    ("sqlalchemy", re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]")),
    ("django", re.compile(r"db_table\s*=\s*['\"](\w+)['\"]")),
    ("django-model", re.compile(r"^class\s+(\w+)\((?:[\w.]*\.)?Model\)", re.MULTILINE)),
    ("laravel", re.compile(r"Schema::(?:create|table)\(\s*['\"](\w+)['\"]")),
    ("prisma", re.compile(r"^model\s+(\w+)\s*\{", re.MULTILINE)),
    ("typeorm", re.compile(r"@Entity\(\s*(?:\{[^}]*name:\s*)?['\"](\w+)['\"]")),
    ("jpa", re.compile(r"@Table\(\s*name\s*=\s*\"(\w+)\"")),
    ("rails", re.compile(r"create_table\s+[:'\"](\w+)")),
    ("efcore", re.compile(r"\.ToTable\(\s*\"(\w+)\"")),
    ("alembic", re.compile(r"op\.create_table\(\s*['\"](\w+)['\"]")),
)
COMMON_SYMBOL_NAMES = frozenset({
    "get", "set", "create", "update", "delete", "list", "index", "show", "store", "destroy", "handle", "main",
    "init", "__init__", "constructor", "render", "run", "execute", "process", "setup", "teardown", "default",
    "props", "data", "config", "app", "router", "test", "build", "save", "find", "load", "apply", "call",
})


@dataclass
class StackItem:
    category: str
    name: str
    version: str | None
    source: str


@dataclass
class FeatureFile:
    path: str
    role: str
    hits: int
    path_match: bool
    samples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SymbolInfo:
    name: str
    kind: str
    path: str
    line: int
    callers: list[dict[str, Any]] = field(default_factory=list)


def classify_role(rel_path: str) -> str:
    for role, pattern in ROLE_RULES:
        if pattern.search(rel_path):
            return role
    return "other"


def split_words(keyword: str) -> list[str]:
    """Split `orderItem`, `order_item`, `order-item` or `order item` into lowercase words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", keyword.strip())
    return [word.lower() for word in re.split(r"[\s_\-./]+", spaced) if word]


def _plural(word: str) -> str:
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    return word + "s"


def feature_pattern(keywords: list[str]) -> re.Pattern[str] | None:
    """Build one case-sensitive regex matching snake/kebab/camel/Pascal/UPPER forms of the keywords.

    Lowercase and UPPER forms require a non-alphanumeric character before them,
    so `order` does not match `border`; the Pascal form matches inside camelCase
    (`createOrder`). The SQL clause `ORDER BY` is excluded explicitly.
    """
    alternatives: set[str] = set()
    for keyword in keywords:
        words = split_words(keyword)
        if not words:
            continue
        for form in (words, [*words[:-1], _plural(words[-1])]):
            lower_forms = {"_".join(form), "-".join(form), " ".join(form)}
            camel = form[0] + "".join(word.capitalize() for word in form[1:])
            pascal = "".join(word.capitalize() for word in form)
            upper = "_".join(word.upper() for word in form)
            for text in lower_forms | {camel}:
                alternatives.add(r"(?<![A-Za-z0-9])" + re.escape(text))
            alternatives.add(re.escape(pascal))
            alternatives.add(r"(?<![A-Za-z0-9])" + re.escape(upper) + r"(?![A-Z])(?!\s+BY\b)")
    if not alternatives:
        return None
    return re.compile("|".join(sorted(alternatives, key=len, reverse=True)))


def _add_stack(items: list[StackItem], mapping: dict[str, tuple[str, str]], name: str, version: str | None, source: str) -> None:
    entry = mapping.get(name.lower()) or mapping.get(name)
    if entry and not any(item.name == entry[1] and item.source == source for item in items):
        items.append(StackItem(entry[0], entry[1], version, source))


def _python_requirement(spec: str) -> tuple[str, str | None] | None:
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)", spec)
    if not match:
        return None
    name = match.group(1).lower().replace("_", "-")
    version = match.group(2).strip() or None
    return name, version


def detect_stack(repo_root: Path, files: list[str]) -> dict[str, Any]:
    """Read manifests (never executing them) to list frameworks, versions, test commands and DB engines."""
    stack: list[StackItem] = []
    test_commands: list[str] = []
    db_engines: list[dict[str, str]] = []
    manifests: list[str] = []
    file_set = set(files)
    package_manager = "npm"
    if "pnpm-lock.yaml" in file_set:
        package_manager = "pnpm"
    elif "yarn.lock" in file_set:
        package_manager = "yarn"
    elif "bun.lockb" in file_set or "bun.lock" in file_set:
        package_manager = "bun"

    for rel_path in files:
        name = PurePosixPath(rel_path).name
        depth = rel_path.count("/")
        if depth > 3:
            continue
        if name == "package.json":
            text = read_text_limited(repo_root / rel_path)
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {}
            manifests.append(rel_path)
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for dependency, version in (data.get(section) or {}).items():
                    _add_stack(stack, NPM_PACKAGES, dependency, str(version), rel_path)
            prefix = "" if depth == 0 else f"(in {PurePosixPath(rel_path).parent}) "
            for script_name in (data.get("scripts") or {}):
                if re.match(r"^(test|e2e|lint|typecheck|type-check|check)(:|$)", script_name):
                    test_commands.append(f"{prefix}{package_manager} run {script_name}")
        elif name == "pyproject.toml":
            text = read_text_limited(repo_root / rel_path)
            try:
                data = tomllib.loads(text) if text else {}
            except tomllib.TOMLDecodeError:
                data = {}
            manifests.append(rel_path)
            specs: list[str] = list((data.get("project") or {}).get("dependencies") or [])
            for group in ((data.get("project") or {}).get("optional-dependencies") or {}).values():
                specs.extend(group)
            for group in (data.get("dependency-groups") or {}).values():
                specs.extend(item for item in group if isinstance(item, str))
            poetry = (data.get("tool") or {}).get("poetry") or {}
            specs.extend(f"{key} {value if isinstance(value, str) else ''}" for key, value in (poetry.get("dependencies") or {}).items())
            for group in (poetry.get("group") or {}).values():
                specs.extend(f"{key}" for key in (group.get("dependencies") or {}))
            for spec in specs:
                parsed = _python_requirement(spec)
                if parsed:
                    _add_stack(stack, PYTHON_PACKAGES, parsed[0], parsed[1], rel_path)
            if "pytest" in json.dumps(data).lower():
                test_commands.append("python -m pytest")
        elif re.match(r"requirements.*\.txt$", name):
            manifests.append(rel_path)
            for line in (read_text_limited(repo_root / rel_path) or "").splitlines():
                parsed = _python_requirement(line) if line.strip() and not line.strip().startswith(("#", "-")) else None
                if parsed:
                    _add_stack(stack, PYTHON_PACKAGES, parsed[0], parsed[1], rel_path)
        elif name == "composer.json":
            text = read_text_limited(repo_root / rel_path)
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {}
            manifests.append(rel_path)
            for section in ("require", "require-dev"):
                for dependency, version in (data.get(section) or {}).items():
                    _add_stack(stack, COMPOSER_PACKAGES, dependency, str(version), rel_path)
            if "artisan" in file_set:
                test_commands.append("php artisan test")
            elif "phpunit.xml" in file_set or "phpunit.xml.dist" in file_set:
                test_commands.append("vendor/bin/phpunit")
        elif name == "go.mod":
            manifests.append(rel_path)
            for match in re.finditer(r"^\s*(?:require\s+)?([\w./-]+)\s+(v[\w.+-]+)", read_text_limited(repo_root / rel_path) or "", re.MULTILINE):
                module = match.group(1)
                for known, entry in GO_MODULES.items():
                    if module.startswith(known):
                        _add_stack(stack, {known: entry}, known, match.group(2), rel_path)
            test_commands.append("go test ./...")
        elif name in ("pom.xml", "build.gradle", "build.gradle.kts"):
            manifests.append(rel_path)
            text = read_text_limited(repo_root / rel_path) or ""
            for artifact, entry in JVM_ARTIFACTS.items():
                if artifact in text:
                    _add_stack(stack, {artifact: entry}, artifact, None, rel_path)
            test_commands.append("mvn test" if name == "pom.xml" else "./gradlew test")
        elif name.endswith(".csproj"):
            manifests.append(rel_path)
            for match in re.finditer(r'PackageReference\s+Include="([^"]+)"(?:\s+Version="([^"]+)")?', read_text_limited(repo_root / rel_path) or ""):
                for prefix, entry in NUGET_PREFIXES.items():
                    if match.group(1).startswith(prefix):
                        _add_stack(stack, {prefix: entry}, prefix, match.group(2), rel_path)
            if "dotnet test" not in test_commands:
                test_commands.append("dotnet test")
        elif name == "Gemfile":
            manifests.append(rel_path)
            for match in re.finditer(r"^\s*gem\s+['\"]([\w-]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", read_text_limited(repo_root / rel_path) or "", re.MULTILINE):
                _add_stack(stack, RUBY_GEMS, match.group(1), match.group(2), rel_path)
        elif name == "Cargo.toml":
            manifests.append(rel_path)
            test_commands.append("cargo test")
        elif re.match(r"(docker-)?compose(\.[\w-]+)?\.ya?ml$", name):
            for match in DB_IMAGE_PATTERN.finditer(read_text_limited(repo_root / rel_path) or ""):
                db_engines.append({"engine": match.group(1).lower(), "version": match.group(2) or "unpinned", "source": rel_path})
        elif name == "schema.prisma":
            provider = re.search(r'provider\s*=\s*"(\w+)"', read_text_limited(repo_root / rel_path) or "")
            if provider and provider.group(1) != "prisma-client-js":
                db_engines.append({"engine": provider.group(1), "version": "see datasource", "source": rel_path})
        elif name in (".env.example", ".env.sample", ".env.template"):
            for match in re.finditer(r"^\s*(?:DATABASE_URL|DB_CONNECTION)\s*=\s*['\"]?(\w+)", read_text_limited(repo_root / rel_path) or "", re.MULTILINE):
                db_engines.append({"engine": match.group(1).lower(), "version": "unknown", "source": rel_path})

    if "Makefile" in file_set:
        for match in re.finditer(r"^(test|lint|check)[\w-]*:", read_text_limited(repo_root / "Makefile") or "", re.MULTILINE):
            test_commands.append(f"make {match.group(0).rstrip(':')}")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in stack:
        grouped.setdefault(item.category, []).append(asdict(item))
    return {
        "by_category": grouped,
        "manifests": manifests,
        "test_commands": list(dict.fromkeys(test_commands)),
        "database_engines": db_engines,
        "package_manager": package_manager if any(path.endswith("package.json") for path in manifests) else None,
    }


def extract_symbols(rel_path: str, text: str) -> list[SymbolInfo]:
    """Definitions in one file: Python via ast, other languages via conservative patterns."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    symbols: list[SymbolInfo] = []
    if suffix == ".py":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return symbols
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(SymbolInfo(node.name, "class", rel_path, node.lineno))
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not member.name.startswith("__"):
                        symbols.append(SymbolInfo(member.name, "method", rel_path, member.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(SymbolInfo(node.name, "function", rel_path, node.lineno))
        return symbols
    patterns: list[tuple[str, re.Pattern[str]]] = []
    if suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"):
        patterns = [
            ("function", re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.MULTILINE)),
            ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:async\s*)?(?:\([^)\n]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=>", re.MULTILINE)),
            ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
            ("type", re.compile(r"^\s*export\s+(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ]
    elif suffix == ".php":
        patterns = [
            ("class", re.compile(r"^\s*(?:final\s+|abstract\s+)?(?:class|interface|trait|enum)\s+(\w+)", re.MULTILINE)),
            ("method", re.compile(r"^\s*(?:public|protected|private)?\s*(?:static\s+)?function\s+(\w+)\s*\(", re.MULTILINE)),
        ]
    elif suffix in (".java", ".kt", ".cs", ".scala"):
        patterns = [
            ("class", re.compile(r"^\s*(?:[\w@]+\s+)*(?:class|interface|enum|record|object)\s+(\w+)", re.MULTILINE)),
            ("method", re.compile(r"^\s*(?:public|protected|private|internal)\s+(?:[\w<>\[\],?]+\s+)*?(\w+)\s*\([^;{]*\)\s*(?:throws [\w., ]+)?\{?\s*$", re.MULTILINE)),
        ]
    elif suffix == ".go":
        patterns = [
            ("function", re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", re.MULTILINE)),
            ("type", re.compile(r"^type\s+(\w+)\s+(?:struct|interface)", re.MULTILINE)),
        ]
    elif suffix == ".rb":
        patterns = [
            ("class", re.compile(r"^\s*(?:class|module)\s+([\w:]+)", re.MULTILINE)),
            ("method", re.compile(r"^\s*def\s+(?:self\.)?(\w+[?!]?)", re.MULTILINE)),
        ]
    keywords = {"if", "for", "while", "switch", "catch", "return", "function", "new", "else"}
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in keywords:
                continue
            symbols.append(SymbolInfo(name, kind, rel_path, text.count("\n", 0, match.start()) + 1))
    return symbols


def find_db_entities(cached_texts: dict[str, str], pattern: re.Pattern[str] | None) -> list[dict[str, Any]]:
    """Collect table/model names from SQL and ORM definitions; entities matching the feature come first."""
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rel_path, text in cached_texts.items():
        for kind, entity_pattern in DB_ENTITY_PATTERNS:
            for match in entity_pattern.finditer(text):
                name = match.group(1)
                if (name.lower(), rel_path) in seen:
                    continue
                seen.add((name.lower(), rel_path))
                entities.append({
                    "name": name,
                    "kind": kind,
                    "path": rel_path,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "matches_feature": bool(pattern and pattern.search(name)) or bool(pattern and pattern.search(name.capitalize())),
                })
    entities.sort(key=lambda entity: (not entity["matches_feature"], entity["name"].lower()))
    return entities[:200]


def build_context_map(repo_root: Path, keywords: list[str], max_files: int) -> dict[str, Any]:
    """Collect mechanical facts for the context map; semantic fields are left for the agent."""
    files, truncated = list_repo_files(repo_root, max_files)
    pattern = feature_pattern(keywords) if keywords else None

    cached_texts: dict[str, str] = {}
    cached_bytes = 0
    secret_files_seen: list[str] = []
    skipped_large_or_binary = 0
    feature_files: list[FeatureFile] = []
    for rel_path in files:
        if is_secret_file(rel_path):
            secret_files_seen.append(rel_path)
            continue
        if is_lockfile(rel_path):
            continue
        text = read_text_limited(repo_root / rel_path, MAX_FILE_BYTES)
        if text is None:
            skipped_large_or_binary += 1
            continue
        if cached_bytes + len(text) <= MAX_CACHED_BYTES:
            cached_texts[rel_path] = text
            cached_bytes += len(text)
        if pattern is None:
            continue
        path_match = bool(pattern.search(rel_path))
        hits = 0
        samples: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits += 1
                if len(samples) < SAMPLE_LINES_PER_FILE:
                    samples.append({"line": line_number, "text": line.strip()[:160]})
        if hits or path_match:
            feature_files.append(FeatureFile(rel_path, classify_role(rel_path), hits, path_match, samples))

    feature_files.sort(key=lambda item: (not item.path_match, -item.hits, item.path))
    top_files = feature_files[:MAX_FEATURE_FILES]

    symbols: list[SymbolInfo] = []
    for feature_file in top_files:
        text = cached_texts.get(feature_file.path)
        if text is None:
            continue
        for symbol in extract_symbols(feature_file.path, text):
            relevant = bool(pattern and pattern.search(symbol.name)) or symbol.kind == "class"
            if relevant and len(symbol.name) >= 4 and symbol.name.lower() not in COMMON_SYMBOL_NAMES:
                symbols.append(symbol)
    symbols = symbols[:MAX_SYMBOLS]
    _attach_callers(symbols, cached_texts)

    instructions = [name for name in INSTRUCTION_FILES if (repo_root / name).is_file()]
    lint_configs = sorted({
        rel_path for rel_path in files
        if rel_path.count("/") <= 1 and any(PurePosixPath(rel_path).match(glob_pattern) for glob_pattern in LINT_CONFIG_PATTERNS)
    })
    by_role: dict[str, list[str]] = {}
    for feature_file in top_files:
        by_role.setdefault(feature_file.role, []).append(feature_file.path)
    reading_order = [path for role in ROLE_READING_ORDER for path in by_role.get(role, [])][:25]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "repository": {"root": str(repo_root), "git": git_snapshot(repo_root)},
        "instructions_to_read_first": instructions,
        "stack": detect_stack(repo_root, files),
        "lint_configs": lint_configs,
        "style": _detect_style(repo_root, files),
        "conventions": detect_conventions(cached_texts, [item.path for item in top_files], pattern),
        "secret_files_not_read": secret_files_seen[:50],
        "feature": {
            "keywords": keywords,
            "files": [asdict(item) for item in top_files],
            "files_total": len(feature_files),
            "suggested_reading_order": reading_order,
            "symbols": [asdict(symbol) for symbol in symbols],
            "db_entities": find_db_entities(cached_texts, pattern),
            "related_tests": [item.path for item in top_files if item.role == "test"],
        },
        "limits": {
            "files_listed": len(files),
            "listing_truncated": truncated,
            "skipped_large_or_binary": skipped_large_or_binary,
            "max_file_bytes": MAX_FILE_BYTES,
            "dynamic_references": "string-based, reflection and DI-container references are not resolved (CTX-005)",
        },
        "agent_must_fill": {
            "conventions_to_follow": [],
            "entry_points_confirmed": [],
            "call_chain": [],
            "invariants": [],
            "transaction_boundaries": [],
            "external_side_effects": [],
            "trust_boundaries": [],
            "other_writers_of_same_tables": [],
            "facts_seen_in_code": [],
            "assumptions": [],
            "unknowns": [],
            "risk": None,
        },
    }


def _detect_style(repo_root: Path, files: list[str]) -> dict[str, Any]:
    """Code-style references per project root; imported here because style_routing builds on detect_stack."""
    from devskills.style_routing import detect_style

    return detect_style(repo_root, files)


def _attach_callers(symbols: list[SymbolInfo], cached_texts: dict[str, str]) -> None:
    """Find references to the symbols with one combined regex pass over the cached files."""
    if not symbols:
        return
    by_name: dict[str, list[SymbolInfo]] = {}
    for symbol in symbols:
        by_name.setdefault(symbol.name, []).append(symbol)
    combined = re.compile(r"(?<![\w$])(" + "|".join(re.escape(name) for name in sorted(by_name, key=len, reverse=True)) + r")(?![\w$])")
    for rel_path, text in cached_texts.items():
        if not any(name in text for name in by_name):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in combined.finditer(line):
                for symbol in by_name[match.group(1)]:
                    if symbol.path == rel_path and symbol.line == line_number:
                        continue
                    if len(symbol.callers) < MAX_CALLERS_PER_SYMBOL:
                        symbol.callers.append({"path": rel_path, "line": line_number, "text": line.strip()[:120]})


def code_graph_section(graph: CodeGraph, repo_root: Path, keywords: list[str], output_dir: Path) -> dict[str, Any]:
    """Add CodeGraph facts when the integration is enabled and available; otherwise record why not."""
    section = graph.to_dict()
    if not graph.available:
        return section
    section["index"] = index_status(graph)
    exploration = explore(graph, keywords)
    if exploration:
        explore_path = output_dir / "codegraph-explore.md"
        atomic_write_text(explore_path, exploration)
        section["explore_file"] = str(explore_path)
    # Tool folders (.codegraph, .devskills, .knowledge) are excluded: only real source changes matter.
    changed = [repo_root / path for path in select_target_files(repo_root, None, "changed", None)
               if (repo_root / path).is_file()][:200]
    tests = affected_tests(graph, changed)
    if tests is not None:
        section["changed_files_checked"] = len(changed)
        section["affected_tests"] = tests
    section["read_only_commands"] = [
        "codegraph explore <words>", "codegraph callers <Symbol> --json",
        "codegraph impact <Symbol> --depth 2 --json", "codegraph affected --json <changed files>",
    ]
    return section


def _render_code_graph(code_graph: dict[str, Any]) -> list[str]:
    lines = ["", "## Code graph (CodeGraph)", ""]
    if not code_graph.get("available"):
        lines.append(f"- mode {code_graph['mode']}: {code_graph['reason']}")
        return lines
    index = code_graph.get("index") or {}
    lines.append(f"- mode {code_graph['mode']}: available ({code_graph.get('version') or 'unknown version'}); "
                 f"index {index.get('files')} files / {index.get('symbols')} symbols, last indexed {index.get('last_indexed')}, "
                 f"pending changes {index.get('pending_changes')}")
    if index.get("reindex_recommended"):
        lines.append("- CodeGraph recommends re-indexing (`codegraph index`); ask the user before running it.")
    if code_graph.get("explore_file"):
        lines.append(f"- exploration (symbols, call paths, blast radius): {code_graph['explore_file']}")
    if "affected_tests" in code_graph:
        tests = code_graph["affected_tests"]
        lines.append(f"- tests affected by the {code_graph['changed_files_checked']} changed file(s): "
                     + (", ".join(tests[:15]) if tests else "none found in the graph"))
    lines.append("- read-only follow-ups: " + " · ".join(f"`{command}`" for command in code_graph["read_only_commands"]))
    return lines


def render_markdown(context_map: dict[str, Any]) -> str:
    """Short human summary; the JSON stays the complete record."""
    git = context_map["repository"]["git"]
    lines = [f"# Context map: {' '.join(context_map['feature']['keywords']) or '(stack only)'}", ""]
    if git.get("is_repo"):
        uncommitted = len(git.get("uncommitted", [])) + len(git.get("untracked", []))
        lines.append(f"- Git: `{git.get('branch')}` @ `{(git.get('head') or '')[:10]}`; "
                     f"{uncommitted} uncommitted/untracked path(s) — preserve developer changes.")
    if context_map["instructions_to_read_first"]:
        lines.append(f"- Read first: {', '.join(context_map['instructions_to_read_first'])}")
    stack = context_map["stack"]
    for category, items in sorted(stack["by_category"].items()):
        rendered = ", ".join(f"{item['name']} {item['version'] or ''}".strip() for item in items[:8])
        lines.append(f"- {category}: {rendered}")
    for engine in stack["database_engines"][:5]:
        lines.append(f"- database engine: {engine['engine']} {engine['version']} ({engine['source']})")
    if stack["test_commands"]:
        lines.append(f"- test commands: {'; '.join(stack['test_commands'][:6])}")
    if context_map["secret_files_not_read"]:
        lines.append(f"- secret files present (not read): {', '.join(context_map['secret_files_not_read'][:5])}")
    for style_root in (context_map.get("style") or {}).get("roots", []):
        if style_root["references"]:
            tools = f"; style tools: {', '.join(style_root['style_tools'])}" if style_root["style_tools"] else ""
            lines.append(f"- code-style for `{style_root['root']}`: {', '.join(style_root['references'])}{tools}")
    if context_map.get("conventions"):
        lines.extend(render_conventions(context_map["conventions"]))
    if context_map.get("code_graph"):
        lines.extend(_render_code_graph(context_map["code_graph"]))
    feature = context_map["feature"]
    if feature["keywords"]:
        lines += ["", f"## Feature files ({feature['files_total']} matched, top {len(feature['files'])})", ""]
        for item in feature["files"][:30]:
            sample = item["samples"][0] if item["samples"] else None
            sample_text = f" — L{sample['line']}: `{sample['text'][:80]}`" if sample else ""
            lines.append(f"- [{item['role']}] {item['path']} ({item['hits']} hits){sample_text}")
        if feature["suggested_reading_order"]:
            lines += ["", "## Suggested reading order", ""]
            lines += [f"{index}. {path}" for index, path in enumerate(feature["suggested_reading_order"][:15], start=1)]
        if feature["symbols"]:
            lines += ["", "## Symbols and callers", ""]
            for symbol in feature["symbols"][:25]:
                callers = ", ".join(f"{caller['path']}:{caller['line']}" for caller in symbol["callers"][:4])
                lines.append(f"- {symbol['kind']} `{symbol['name']}` {symbol['path']}:{symbol['line']}"
                             + (f" ← {callers}" if callers else " ← (no static callers found)"))
        related_entities = [entity for entity in feature["db_entities"] if entity["matches_feature"]][:15]
        if related_entities:
            lines += ["", "## DB entities", ""]
            lines += [f"- {entity['name']} ({entity['kind']}) {entity['path']}:{entity['line']}" for entity in related_entities]
    lines += ["", "## Agent must fill before designing",
              "conventions to follow (reference module, bases/helpers to reuse), entry points confirmed, call chain, invariants, transaction boundaries, other writers of the same tables,",
              "external side effects, trust boundaries, facts vs assumptions vs unknowns, risk level."]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    """CLI handler for `inspect`: write context-map.json/.md (into the run with --run) and record context.map."""
    repo_root = resolve_repo_root(args.repo)
    profile, _profile_warnings = load_profile(repo_root)
    started_at = utc_now_iso()
    keywords = args.feature or []
    graph = detect(repo_root, resolve_mode(args.codegraph, profile))
    context_map = build_context_map(repo_root, keywords, args.max_files)

    if args.run:
        output_dir = artifacts_dir(repo_root, args.run)
    else:
        output_dir = ensure_state_dir(repo_root) / "context"
    context_map["code_graph"] = code_graph_section(graph, repo_root, keywords, output_dir)
    markdown = render_markdown(context_map)
    json_path = output_dir / "context-map.json"
    markdown_path = Path(args.markdown) if args.markdown else output_dir / "context-map.md"
    atomic_write_json(json_path, context_map)
    atomic_write_text(markdown_path, markdown)

    feature_found = bool(context_map["feature"]["files"]) or not keywords
    # With codegraph=on the graph is expected; its absence is surfaced instead of silently ignored.
    graph_missing = graph.mode == "on" and not graph.available
    summary = (f"{context_map['feature']['files_total']} feature files, {len(context_map['feature']['symbols'])} symbols; "
               "semantic fields still need the agent's reading")
    if graph_missing:
        summary += f"; codegraph=on but {graph.reason}"
    result = CheckResult(
        check_id=getattr(args, "check_id", "context.map"),
        tool="devskills.inspect",
        execution_status=EXEC_COMPLETED,
        gate_result=GATE_PASS if feature_found and not graph_missing else GATE_WARN,
        domain_result="context_map_generated" if feature_found else "feature_not_found",
        summary=summary,
        details={"context_map": str(json_path), "markdown": str(markdown_path), "keywords": keywords,
                 "code_graph": context_map["code_graph"]},
        evidence_refs=[str(json_path), str(markdown_path)] + (
            [context_map["code_graph"]["explore_file"]] if context_map["code_graph"].get("explore_file") else []),
        started_at=started_at,
    )
    if getattr(args, "json", False):
        return emit_result(args, repo_root, result, [])
    return emit_result(args, repo_root, result, [markdown, f"context map: {json_path}"])
