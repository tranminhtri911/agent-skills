"""Native stack checks: the project's own typecheck, lint, build and framework checks.

These are the primary evidence for code correctness; `check-code` regex rules are
only a supporting layer. Commands come from manifests (package.json scripts,
pyproject/manage.py, composer.json, go.mod, Cargo.toml, *.csproj, Makefile) and
run through `runner.execute_check`, so they get the same env allowlist,
preflight, network isolation, timeout and redacted logs as `run-tests`.

Rules that keep this safe:
- never download tools: `npx`, `pnpm dlx`, `go run pkg@version` are not used;
  missing dependencies make a check `blocked`, they are not installed;
- a package.json script (or its pre/post hook) that looks like deploy/publish/
  network/delete is not run; it is reported for the user to review;
- exit 0 counts as pass only for typecheck/lint/build/framework kinds; test
  commands still need a parsed report (TEST-010).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from devskills.fsutil import list_repo_files, read_text_limited, resolve_repo_root, select_target_files, utc_now_iso
from devskills.models import (
    EXEC_NOT_RUN,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    UsageError,
    exit_code_for_gate,
)
from devskills.runner import execute_check
from devskills.runs import record_check

KINDS = ("typecheck", "lint", "build", "framework", "migrations", "test")
DEFAULT_KINDS = ("typecheck", "lint", "build", "framework", "migrations")
MAX_MANIFEST_DEPTH = 3
SCRIPT_ALIASES = {
    "typecheck": ("typecheck", "type-check", "check-types", "types", "tsc"),
    "lint": ("lint",),
    "build": ("build",),
    "test": ("test",),
}
# Script bodies that must not run unattended (side effects outside the working tree).
UNSAFE_SCRIPT = re.compile(
    r"(?i)\b(deploy|publish|release|upload|push|rsync|scp|ssh|curl|wget|aws|gcloud|az|firebase|vercel|netlify|"
    r"heroku|kubectl|helm|terraform|docker\s+(push|login)|rm\s+-rf?\s+[/~]|sudo|npx|dlx)\b")
CI_ENV = ["CI=true", "NO_UPDATE_NOTIFIER=1", "npm_config_update_notifier=false", "NEXT_TELEMETRY_DISABLED=1",
          "DOTNET_CLI_TELEMETRY_OPTOUT=1", "PYTHONDONTWRITEBYTECODE=1"]
PYTHON_VENV_DIRS = (".venv", "venv", "env")


@dataclass
class NativeCheck:
    """One planned command, or the reason it cannot run."""

    check_id: str
    kind: str
    subproject: str
    tool: str
    argv: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
    junit_path: str | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value not in (None, "", [])}


def _check_id(kind: str, subproject: str) -> str:
    """`native.<kind>` for the root, `native.<kind>.<dir-slug>` for nested projects (≤64 chars)."""
    if subproject in ("", "."):
        return f"native.{kind}"
    slug = re.sub(r"[^a-z0-9]+", "-", subproject.lower()).strip("-")[:40] or "sub"
    return f"native.{kind}.{slug}"


def _first_existing(directory: Path, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if (directory / name).exists()), None)


def find_project_dirs(repo_root: Path) -> dict[str, set[str]]:
    """Map subproject dir (relative, '' = root) to the manifest names it holds."""
    files, _ = list_repo_files(repo_root)
    manifest_names = {"package.json", "pyproject.toml", "manage.py", "setup.cfg", "requirements.txt", "composer.json",
                      "go.mod", "Cargo.toml", "Makefile"}
    projects: dict[str, set[str]] = {}
    for rel_path in files:
        path = PurePosixPath(rel_path)
        if len(path.parts) > MAX_MANIFEST_DEPTH + 1:
            continue
        name = path.name
        if name in manifest_names or path.suffix in (".csproj", ".sln", ".tf"):
            directory = "" if str(path.parent) == "." else str(path.parent)
            projects.setdefault(directory, set()).add(name if path.suffix not in (".csproj", ".sln", ".tf") else path.suffix)
    # Terraform: only the top-most folder with .tf files is a project (fmt -recursive and scanners cover modules below).
    tf_dirs = {directory for directory, names in projects.items() if ".tf" in names}
    for directory in tf_dirs:
        if any(other != directory and (other == "" or directory.startswith(other + "/")) for other in tf_dirs):
            projects[directory].discard(".tf")
            if not projects[directory]:
                del projects[directory]
    return projects


# --------------------------------------------------------------------------- per-ecosystem planners


def _node_package_manager(project: Path, repo_root: Path) -> str:
    for directory in (project, repo_root):
        for lockfile, manager in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"),
                                  ("bun.lock", "bun"), ("package-lock.json", "npm")):
            if (directory / lockfile).exists():
                return manager
    return "npm"


def _plan_node(project: Path, sub: str, repo_root: Path, kinds: set[str]) -> list[NativeCheck]:
    try:
        package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [NativeCheck(_check_id("build", sub), "build", sub, "node", blocked_reason=f"package.json unreadable: {error}")]
    scripts: dict[str, str] = package.get("scripts") or {}
    manager = _node_package_manager(project, repo_root)
    bin_dir = project / "node_modules" / ".bin"
    if not bin_dir.is_dir():
        bin_dir = repo_root / "node_modules" / ".bin"  # Workspace root install.
    installed = bin_dir.is_dir()
    checks: list[NativeCheck] = []
    for kind in ("typecheck", "lint", "build", "test"):
        if kind not in kinds:
            continue
        check_id = _check_id(kind, sub)
        script = next((name for name in SCRIPT_ALIASES[kind] if name in scripts), None)
        if script and kind == "test" and "no test specified" in scripts[script]:
            script = None
        if script:
            bodies = " && ".join(scripts.get(name, "") for name in (f"pre{script}", script, f"post{script}"))
            if UNSAFE_SCRIPT.search(bodies):
                checks.append(NativeCheck(check_id, kind, sub, manager, source=f"package.json scripts.{script}",
                                          blocked_reason=f"script `{script}` (or its pre/post hook) has side effects "
                                                         f"({UNSAFE_SCRIPT.search(bodies).group(0)}); review and run it yourself"))
                continue
            if shutil.which(manager) is None:
                checks.append(NativeCheck(check_id, kind, sub, manager, blocked_reason=f"{manager} is not on PATH"))
                continue
            blocked = None if installed else "node_modules missing; install dependencies first (native checks never download)"
            checks.append(NativeCheck(check_id, kind, sub, manager, [manager, "run", script], blocked_reason=blocked,
                                      source=f"package.json scripts.{script}"))
        elif kind == "typecheck" and (project / "tsconfig.json").exists():
            tsc = bin_dir / "tsc"
            checks.append(NativeCheck(check_id, kind, sub, "tsc", [str(tsc), "--noEmit", "-p", "tsconfig.json"],
                                      blocked_reason=None if tsc.exists() else "typescript not installed in node_modules",
                                      source="tsconfig.json"))
        elif kind == "lint" and (_first_existing(project, ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
                                                            "eslint.config.ts", ".eslintrc.js", ".eslintrc.cjs",
                                                            ".eslintrc.json", ".eslintrc.yml", ".eslintrc"))
                                 or "eslintConfig" in package):
            eslint = bin_dir / "eslint"
            checks.append(NativeCheck(check_id, kind, sub, "eslint", [str(eslint), "."],
                                      blocked_reason=None if eslint.exists() else "eslint not installed in node_modules",
                                      source="eslint config"))
    return checks


def project_python(project: Path, repo_root: Path) -> str | None:
    """The project's own interpreter (its venv) first, then python3 on PATH."""
    for directory in (project, repo_root):
        for venv in PYTHON_VENV_DIRS:
            for candidate in (directory / venv / "bin" / "python", directory / venv / "Scripts" / "python.exe"):
                if candidate.exists():
                    return str(candidate)
    return shutil.which("python3") or shutil.which("python")


def _python_has(python: str, module: str) -> bool:
    """True when `module` is importable by that interpreter (checked by finding its files, not importing)."""
    venv_root = Path(python).parent.parent
    for site in list(venv_root.glob("lib/python3*/site-packages")) + [venv_root / "Lib" / "site-packages"]:
        if (site / module).exists() or (site / f"{module}.py").exists() or any(site.glob(f"{module}-*.dist-info")):
            return True
    return Path(python).parent.joinpath(module).exists()


def _plan_python(project: Path, sub: str, repo_root: Path, kinds: set[str], log_hint: str) -> list[NativeCheck]:
    python = project_python(project, repo_root)
    if python is None:
        return [NativeCheck(_check_id("lint", sub), "lint", sub, "python", blocked_reason="no python interpreter found")]
    pyproject = read_text_limited(project / "pyproject.toml", 512 * 1024) or ""
    setup_cfg = read_text_limited(project / "setup.cfg", 256 * 1024) or ""
    checks: list[NativeCheck] = []

    def add(kind: str, module: str, args: list[str], source: str) -> None:
        if kind not in kinds:
            return
        blocked = None if _python_has(python, module) else f"{module} is not installed in {python}"
        checks.append(NativeCheck(_check_id(kind, sub), kind, sub, module, [python, "-m", module, *args],
                                  blocked_reason=blocked, source=source))

    if "[tool.ruff" in pyproject or _first_existing(project, ("ruff.toml", ".ruff.toml")):
        add("lint", "ruff", ["check", "."], "ruff config")
    elif "[flake8]" in setup_cfg or (project / ".flake8").exists():
        add("lint", "flake8", ["."], "flake8 config")
    mypy_ini = read_text_limited(project / "mypy.ini", 64 * 1024) or ""
    if "[tool.mypy" in pyproject or mypy_ini or "[mypy" in setup_cfg:
        # Respect a configured `files =` list; otherwise check the project folder.
        configured_files = re.search(r"(?m)^files\s*=", pyproject + "\n" + mypy_ini + "\n" + setup_cfg)
        add("typecheck", "mypy", [] if configured_files else ["."], "mypy config")
    elif (project / "pyrightconfig.json").exists() or "[tool.pyright" in pyproject:
        add("typecheck", "pyright", [], "pyright config")
    if (project / "manage.py").exists():
        for kind, args in (("framework", ["check"]), ("migrations", ["makemigrations", "--check", "--dry-run"])):
            if kind in kinds:
                checks.append(NativeCheck(_check_id(kind, sub), kind, sub, "django", [python, "manage.py", *args],
                                          source="manage.py"))
    if "test" in kinds:
        uses_pytest = ("[tool.pytest" in pyproject or "[tool:pytest]" in setup_cfg
                       or _first_existing(project, ("pytest.ini", "conftest.py")) is not None)
        if uses_pytest:
            junit = f"{log_hint}/junit-{_check_id('test', sub)}.xml"
            add("test", "pytest", ["-q", f"--junitxml={junit}"], "pytest config")
            if checks and checks[-1].kind == "test":
                checks[-1].junit_path = junit
        elif (project / "manage.py").exists():
            checks.append(NativeCheck(_check_id("test", sub), "test", sub, "django", [python, "manage.py", "test"],
                                      source="manage.py (no JUnit: result stays warn)"))
    return checks


def _plan_php(project: Path, sub: str, kinds: set[str], log_hint: str) -> list[NativeCheck]:
    checks: list[NativeCheck] = []
    php = shutil.which("php")
    vendor = project / "vendor" / "bin"

    def add(kind: str, binary: str, args: list[str], source: str, junit: str | None = None) -> None:
        if kind not in kinds:
            return
        path = vendor / binary
        blocked = None if path.exists() else f"vendor/bin/{binary} missing; run composer install yourself"
        argv = [str(path), *args]
        checks.append(NativeCheck(_check_id(kind, sub), kind, sub, binary, argv, blocked, junit, source))

    if (vendor / "pint").exists() or (project / "pint.json").exists():
        add("lint", "pint", ["--test"], "laravel/pint")
    elif _first_existing(project, (".php-cs-fixer.php", ".php-cs-fixer.dist.php")):
        add("lint", "php-cs-fixer", ["fix", "--dry-run", "--diff"], "php-cs-fixer config")
    if _first_existing(project, ("phpstan.neon", "phpstan.neon.dist", "phpstan.dist.neon")):
        add("typecheck", "phpstan", ["analyse", "--no-progress"], "phpstan config")
    if "test" in kinds:
        junit = f"{log_hint}/junit-{_check_id('test', sub)}.xml"
        if (project / "artisan").exists() and php:
            checks.append(NativeCheck(_check_id("test", sub), "test", sub, "artisan",
                                      [php, "artisan", "test", f"--log-junit={junit}"], junit_path=junit,
                                      source="artisan test",
                                      blocked_reason=None if vendor.is_dir() else "vendor/ missing; run composer install yourself"))
        elif (project / "phpunit.xml").exists() or (project / "phpunit.xml.dist").exists():
            add("test", "phpunit", [f"--log-junit={junit}"], "phpunit.xml", junit)
    return checks


def _plan_go(sub: str, kinds: set[str]) -> list[NativeCheck]:
    go = shutil.which("go")
    plan = [("lint", ["vet", "./..."]), ("build", ["build", "./..."]), ("test", ["test", "./..."])]
    return [NativeCheck(_check_id(kind, sub), kind, sub, "go", [go or "go", *args], None if go else "go is not on PATH",
                        source="go.mod") for kind, args in plan if kind in kinds]


def _plan_rust(sub: str, kinds: set[str]) -> list[NativeCheck]:
    cargo = shutil.which("cargo")
    plan = [("typecheck", ["check", "--offline"]), ("build", ["build", "--offline"]), ("test", ["test", "--offline"])]
    return [NativeCheck(_check_id(kind, sub), kind, sub, "cargo", [cargo or "cargo", *args],
                        None if cargo else "cargo is not on PATH", source="Cargo.toml") for kind, args in plan if kind in kinds]


def _plan_dotnet(project: Path, sub: str, kinds: set[str]) -> list[NativeCheck]:
    project_files = sorted(project.glob("*.sln")) or sorted(project.glob("*.csproj"))
    if "build" not in kinds or not project_files:
        return []
    target = project_files[0]
    check_id = _check_id("build", sub)
    # A solution's projects live one level down; read them to tell SDK-style from classic.
    csproj_paths = sorted(project.glob("*.csproj")) or sorted(project.glob("*/*.csproj"))[:30]
    csproj_texts = [read_text_limited(path, 64 * 1024) or "" for path in csproj_paths]
    # Classic (non SDK-style) projects need MSBuild + .NET Framework reference assemblies.
    if csproj_texts and not all(re.search(r"<Project\s+Sdk=", text) for text in csproj_texts):
        reason = ("classic .NET Framework project: build with MSBuild on Windows (Visual Studio Build Tools)"
                  if sys.platform != "win32" else "classic .NET Framework project: run msbuild from a Developer prompt")
        return [NativeCheck(check_id, "build", sub, "msbuild", blocked_reason=reason, source=target.name)]
    dotnet = shutil.which("dotnet")
    return [NativeCheck(check_id, "build", sub, "dotnet", [dotnet or "dotnet", "build", target.name, "--no-restore", "-nologo"],
                        None if dotnet else "dotnet SDK is not on PATH", source=target.name)]


def _plan_terraform(project: Path, sub: str, kinds: set[str]) -> list[NativeCheck]:
    """fmt and validate, plus checkov/trivy/tflint when installed. Never init/plan/apply: no state, no cloud access."""
    terraform = shutil.which("terraform") or shutil.which("tofu")
    tool = Path(terraform).name if terraform else "terraform"
    missing = None if terraform else "terraform/tofu is not on PATH"
    checks = []
    if "lint" in kinds:
        checks.append(NativeCheck(_check_id("lint", sub), "lint", sub, tool, [terraform or tool, "fmt", "-check", "-recursive", "-diff"],
                                  missing, source="*.tf"))
    if "typecheck" in kinds:
        uninitialized = None if (project / ".terraform").is_dir() else (
            f"not initialized: the user runs `{tool} init -backend=false` (downloads providers, no state access)")
        checks.append(NativeCheck(_check_id("typecheck", sub), "typecheck", sub, tool, [terraform or tool, "validate", "-no-color"],
                                  missing or uninitialized, source="*.tf"))
    if "lint" in kinds:
        scanners = [("checkov", ["-d", ".", "--compact", "--quiet", "--skip-download"]),
                    ("trivy", ["config", "--skip-check-update", "--exit-code", "1", "."])]
        if (project / ".tflint.hcl").is_file():
            scanners.append(("tflint", ["--recursive"]))
        for name, scanner_args in scanners:
            executable = shutil.which(name)
            if executable:
                checks.append(NativeCheck(_check_id("lint", sub), "lint", sub, name, [executable, *scanner_args], source=name))
    return checks


def _plan_make(project: Path, sub: str, kinds: set[str], covered: set[str]) -> list[NativeCheck]:
    text = read_text_limited(project / "Makefile", 256 * 1024) or ""
    targets = set(re.findall(r"(?m)^([A-Za-z][\w-]*)\s*:", text))
    make = shutil.which("make")
    checks = []
    for kind, names in (("typecheck", ("typecheck", "type-check")), ("lint", ("lint",)), ("build", ("build",))):
        target = next((name for name in names if name in targets), None)
        if kind in kinds and kind not in covered and target:
            recipe = re.search(rf"(?ms)^{re.escape(target)}\s*:.*?(?=^\S|\Z)", text)
            unsafe = UNSAFE_SCRIPT.search(recipe.group(0)) if recipe else None
            checks.append(NativeCheck(_check_id(kind, sub), kind, sub, "make", [make or "make", target],
                                      blocked_reason=(f"make {target} has side effects ({unsafe.group(0)}); review it yourself"
                                                      if unsafe else None if make else "make is not on PATH"),
                                      source=f"Makefile:{target}"))
    return checks


def plan_checks(repo_root: Path, kinds: set[str], only_dirs: set[str] | None = None,
                log_hint: str = ".devskills/native") -> list[NativeCheck]:
    """Plan native checks per subproject; `only_dirs` limits it to projects touched by a change."""
    planned: list[NativeCheck] = []
    for sub, manifests in sorted(find_project_dirs(repo_root).items()):
        if only_dirs is not None and sub not in only_dirs:
            continue
        project = repo_root / sub if sub else repo_root
        checks: list[NativeCheck] = []
        if "package.json" in manifests:
            checks += _plan_node(project, sub, repo_root, kinds)
        if manifests & {"pyproject.toml", "manage.py", "setup.cfg", "requirements.txt"}:
            checks += _plan_python(project, sub, repo_root, kinds, log_hint)
        if "composer.json" in manifests:
            checks += _plan_php(project, sub, kinds, log_hint)
        if "go.mod" in manifests:
            checks += _plan_go(sub, kinds)
        if "Cargo.toml" in manifests:
            checks += _plan_rust(sub, kinds)
        if manifests & {".csproj", ".sln"}:
            checks += _plan_dotnet(project, sub, kinds)
        if ".tf" in manifests:
            checks += _plan_terraform(project, sub, kinds)
        if "Makefile" in manifests:
            checks += _plan_make(project, sub, kinds, {check.kind for check in checks})
        # Two ecosystems in one folder (e.g. Laravel + Vite) may plan the same id: suffix the tool.
        seen: set[str] = set()
        for check in checks:
            if check.check_id in seen:
                check.check_id = f"{check.check_id}-{check.tool}"[:64]
            seen.add(check.check_id)
        planned += checks
    return planned


def touched_project_dirs(repo_root: Path, changed_paths: list[str]) -> set[str]:
    """Subproject dirs that contain at least one changed path (deepest match wins)."""
    projects = sorted(find_project_dirs(repo_root), key=len, reverse=True)
    touched: set[str] = set()
    for path in changed_paths:
        owner = next((sub for sub in projects if sub == "" or path == sub or path.startswith(sub + "/")), None)
        if owner is not None:
            touched.add(owner)
    return touched


def _blocked_result(check: NativeCheck) -> CheckResult:
    return CheckResult(check_id=check.check_id, tool=f"devskills.native-checks/{check.tool}", execution_status=EXEC_NOT_RUN,
                       gate_result=GATE_BLOCKED, domain_result="not_runnable", summary=check.blocked_reason or "",
                       details={"kind": check.kind, "subproject": check.subproject or ".", "source": check.source})


def run(args: argparse.Namespace) -> int:
    """CLI handler for `native-checks`: plan (default) or run the stack's own checks."""
    repo_root = resolve_repo_root(args.repo)
    kinds = set(args.kinds.split(",")) if args.kinds else set(DEFAULT_KINDS)
    unknown = kinds - set(KINDS)
    if unknown:
        raise UsageError(f"unknown kinds: {', '.join(sorted(unknown))} (choose from {', '.join(KINDS)})")
    only_dirs = None
    if not args.all_projects:
        changed = select_target_files(repo_root, args.paths, "changed", args.base)
        only_dirs = touched_project_dirs(repo_root, changed) if changed else None
    log_hint = str((repo_root / ".devskills" / "native").resolve())
    checks = plan_checks(repo_root, kinds, only_dirs, log_hint)
    if args.only:
        wanted = set(args.only)
        checks = [check for check in checks if check.check_id in wanted]

    if not args.execute:
        if args.json:
            print(json.dumps({"checks": [check.to_dict() for check in checks]}, indent=2, ensure_ascii=False))
        else:
            print(f"native checks ({'changed projects' if only_dirs is not None else 'all projects'}):")
            for check in checks:
                state = f"BLOCKED: {check.blocked_reason}" if check.blocked_reason else " ".join(check.argv)
                print(f"  {check.check_id:32} {state}")
            if not checks:
                print("  none detected; record evidence with run-tests or waive with a reason")
            print("Run them with --execute (add --run RUN_ID to record evidence).")
        return 0

    Path(log_hint).mkdir(parents=True, exist_ok=True)
    worst = GATE_PASS
    rank = {GATE_PASS: 0, GATE_WARN: 1, GATE_BLOCKED: 2, GATE_FAIL: 3}
    summaries = []
    for check in checks:
        if check.blocked_reason:
            result, lines = _blocked_result(check), [f"{check.check_id}: BLOCKED — {check.blocked_reason}"]
        else:
            cwd = repo_root / check.subproject if check.subproject else repo_root
            result, lines = execute_check(
                repo_root, check.argv, check_id=check.check_id, profile_name=args.profile,
                junit_patterns=[check.junit_path] if check.junit_path else [], timeout=args.timeout,
                extra_env=CI_ENV + list(args.env), env_files=args.env_file, cwd=cwd, run_id=args.run,
                exit_code_is_evidence=check.kind != "test")
            result.tool = f"devskills.native-checks/{check.tool}"
            result.details |= {"kind": check.kind, "subproject": check.subproject or ".", "source": check.source}
        result.finished_at = result.finished_at or utc_now_iso()
        recorded = record_check(repo_root, args.run, result) if args.run else None
        if not args.json:
            print("\n".join([*lines, f"gate: {result.gate_result}  ({result.summary})"]
                            + ([f"recorded: {recorded}"] if recorded else [])))
        summaries.append(result.to_dict())
        worst = max(worst, result.gate_result, key=lambda gate: rank.get(gate, 2))
    if args.json:
        print(json.dumps({"overall": worst, "checks": summaries}, indent=2, ensure_ascii=False))
    else:
        print(f"native-checks overall: {worst} ({len(checks)} check(s))")
    return exit_code_for_gate(worst) if checks else exit_code_for_gate(GATE_WARN)


def planned_ids_for_roster(repo_root: Path, changed_paths: list[str]) -> list[tuple[str, str]]:
    """(check_id, kind) for native checks in the projects a change touches; used by `roster init`."""
    touched = touched_project_dirs(repo_root, changed_paths)
    if not touched:
        return []
    return [(check.check_id, check.kind) for check in plan_checks(repo_root, set(DEFAULT_KINDS), touched)]


