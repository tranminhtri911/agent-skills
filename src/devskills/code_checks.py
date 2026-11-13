"""Language-aware static checks for maintainability, safety and resource rules.

Findings are review signals with a severity, not verdicts: the agent triages
them with judgment (plan §25.4). Python is analysed with `ast`; other languages
use conservative patterns on code whose strings and comments are masked, which
keeps false positives low at the cost of missing some cases.

Inline exception: `devskills:ignore RULE-ID reason` on the same or previous
line suppresses that rule there; a reason is mandatory and wildcards are not
supported (plan §4.5).
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from devskills.domain_values import hardcoded_value_findings, index_repository
from devskills.fsutil import is_lockfile, is_secret_file, read_text_limited, resolve_repo_root, select_target_files, utc_now_iso
from devskills.models import EXEC_COMPLETED, CheckResult, Finding, gate_from_findings
from devskills.output import emit_result, format_findings, severity_summary
from devskills.profile import load_profile
from devskills.security_rules import pattern_findings, python_security_findings

PY_SUFFIXES = frozenset({".py", ".pyi"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
SFC_SUFFIXES = frozenset({".vue", ".svelte"})
PHP_SUFFIXES = frozenset({".php"})
C_LIKE_SUFFIXES = frozenset({".java", ".kt", ".kts", ".cs", ".scala", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".dart"})
GO_SUFFIXES = frozenset({".go"})
RUBY_SUFFIXES = frozenset({".rb"})
HASH_COMMENT_SUFFIXES = frozenset({".rb", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".r", ".pl", ".ps1"})
SUPPORTED_SUFFIXES = (PY_SUFFIXES | JS_SUFFIXES | SFC_SUFFIXES | PHP_SUFFIXES | C_LIKE_SUFFIXES | GO_SUFFIXES
                      | RUBY_SUFFIXES | HASH_COMMENT_SUFFIXES)

# Names that usually hold money; rate/ratio/percent/time/count suffixes are excluded.
MONEY_NAME = re.compile(
    r"(?i)(amount|price|balance|fee|cost|tax|discount|refund|salary|wage|money|subtotal|grand_?total|total_?(amount|price))"
    r"(?!\w*(rate|ratio|percent|pct|seconds|secs|ms|count|_id|ids)\b)"
)
SECURITY_VALUE_NAME = re.compile(r"(?i)(token|secret|password|passwd|otp|nonce|salt|api_?key|session_?id|reset_?code|verification_?code)")
# A TODO marker must open the comment; prose that merely mentions "TODO" is not a task.
TODO_PATTERN = re.compile(r"^\s*(?:#|//|/\*+|\*|--|<!--)?\s*(TODO|FIXME|XXX|HACK)\b", re.MULTILINE)
TODO_HAS_OWNER = re.compile(r"\b(TODO|FIXME|XXX|HACK)\s*[\(\[]\s*[@\w.-]+|#\d+|\b[A-Z][A-Z0-9]+-\d+\b|@\w+|https?://")
# Rule ids are separated by mandatory spaces/commas, which keeps the regex free of nested quantifiers.
SUPPRESSION = re.compile(r"devskills:ignore\s+([A-Z][A-Z0-9-]+(?:[ ,]+[A-Z][A-Z0-9-]+)*)\s*(.*)")
DIRECTIVE_COMMENT = re.compile(
    r"^\s*(//|#)\s*(eslint|prettier|@ts-|tslint|#?region|#?endregion|noinspection|NOSONAR|istanbul|c8|jshint|global\b|"
    r"<reference|pragma|nolint|go:|\+build|phpcs|@phpstan|rubocop|frozen_string_literal|-\*-|type:|noqa|pylint|fmt:)"
)
CODE_LIKE_COMMENT = re.compile(r"^\s*(//|#)\s*((import|export|const|let|var|return|if|for|while|function|class|public|private|await|\$\w+)\b.*|.*[;{}]\s*$)")

REQUESTS_FUNCTIONS = frozenset({f"requests.{verb}" for verb in ("get", "post", "put", "patch", "delete", "head", "options", "request")})
BLOCKING_IN_ASYNC = frozenset({"time.sleep", "urllib.request.urlopen", *REQUESTS_FUNCTIONS})
SUBPROCESS_BLOCKING = frozenset({"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "os.system"})
TRANSACTION_CONTEXTS = frozenset({"transaction.atomic", "atomic", "django.db.transaction.atomic", "db.transaction.atomic"})
SLOW_IN_TRANSACTION = frozenset({
    *BLOCKING_IN_ASYNC, *SUBPROCESS_BLOCKING, "urlopen", "asyncio.sleep",
    *{f"httpx.{verb}" for verb in ("get", "post", "put", "patch", "delete", "head", "options", "request", "stream")},
    "send_mail", "send_mass_mail", "mail.send_mail", "django.core.mail.send_mail", "smtplib.SMTP", "smtplib.SMTP_SSL",
})
SQL_SINK_ATTRIBUTES = frozenset({"execute", "executemany", "executescript", "exec_driver_sql", "raw", "extra", "query"})
SQL_TEXT_FUNCTIONS = frozenset({"text", "sqlalchemy.text", "sa.text"})
FACTORY_FUNCTION = re.compile(r"^(create|make|build|get|init|setup|configure|connect|lifespan|main|_create|_make|_build|_get|_init)")
UNITTEST_CAMEL_NAMES = frozenset({
    "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule", "tearDownModule", "asyncSetUp", "asyncTearDown",
    "addCleanup", "runTest", "shortDescription", "maxDiff",
})
VAGUE_FUNCTION_NAMES = frozenset({
    "do_stuff", "do_it", "doit", "do_something", "handle_stuff", "process_stuff", "func", "foo", "bar", "baz",
    "helper", "helper1", "stuff", "thing", "test1", "temp", "tmp", "my_function", "main2",
})
VAGUE_VARIABLE_NAMES = frozenset({"tmp", "temp", "foo", "bar", "baz", "qux", "xxx", "stuff", "thing", "data2", "obj2", "my_var", "var1"})
NARROW_EXCEPTIONS = frozenset({"KeyError", "FileNotFoundError", "ProcessLookupError", "StopIteration", "StopAsyncIteration",
                               "IndexError", "AttributeError", "NotImplementedError", "FileExistsError", "ImportError",
                               "ModuleNotFoundError", "PermissionError", "LookupError", "BrokenPipeError",
                               "ConnectionResetError", "ConnectionAbortedError", "InterruptedError", "KeyboardInterrupt",
                               "UnicodeDecodeError", "csv.Error", "json.JSONDecodeError", "ValueError"})


@dataclass(frozen=True)
class CheckSettings:
    multiline_comment_style: str
    max_function_lines: int
    doc_min_lines: int
    hardcoded_values: bool = True


def is_test_path(rel_path: str) -> bool:
    return bool(re.search(
        r"(^|/)(tests?|__tests__|spec|specs|e2e|testing|fixtures)(/|$)|(_test|\.test|\.spec)\.\w+$|"
        r"(^|/)test_[^/]+$|(Test|Tests|Spec)\.\w+$|conftest\.py$", rel_path))


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(rule_id: str, severity: str, message: str, path: str, line: int | None, hint: str | None = None) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, path=path, line=line, hint=hint)


# --------------------------------------------------------------------------- Python


def _dotted_name(node: ast.AST) -> str | None:
    """Return 'a.b.c' for Name/Attribute chains (calls become 'f()'), else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        inner = _dotted_name(node.func)
        if inner:
            parts.append(inner + "()")
            return ".".join(reversed(parts))
    return None


def _is_transaction_context(node: ast.AST) -> bool:
    """True for `transaction.atomic()`, `@atomic`, `session.begin()`, `engine.begin()` and similar unit-of-work openers."""
    target = node.func if isinstance(node, ast.Call) else node
    name = _dotted_name(target) or ""
    return name in TRANSACTION_CONTEXTS or (isinstance(target, ast.Attribute) and target.attr == "begin")


def _is_string_building(node: ast.AST) -> bool:
    """True for f-strings with placeholders, `%`/`+` on string literals and `.format()` calls."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(value, ast.FormattedValue) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return any(isinstance(side, (ast.Constant, ast.JoinedStr)) and (not isinstance(side, ast.Constant) or isinstance(side.value, str))
                   for side in (node.left, node.right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)
    return False


def _target_names(targets: list[ast.AST]) -> list[str]:
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(_target_names(list(target.elts)))
    return names


class _PythonVisitor(ast.NodeVisitor):
    """Collect findings while tracking function, loop and nesting context."""

    def __init__(self, rel_path: str, settings: CheckSettings, is_test: bool, lines: list[str]):
        self.rel_path = rel_path
        self.settings = settings
        self.is_test = is_test
        self.lines = lines
        self.findings: list[Finding] = []
        self.function_stack: list[tuple[ast.AST, bool]] = []
        self.class_depth = 0
        self.loop_depth = 0
        self.block_depth = 0
        self.nesting_reported: set[int] = set()
        self.transaction_depth = 0

    def add(self, node: ast.AST, rule_id: str, severity: str, message: str, hint: str | None = None) -> None:
        self.findings.append(_finding(rule_id, severity, message, self.rel_path, getattr(node, "lineno", None), hint))

    @property
    def in_async_function(self) -> bool:
        return bool(self.function_stack) and self.function_stack[-1][1]

    # Definitions -----------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        self._check_defaults(node)
        self._check_function_name(node)
        self._check_money_arguments(node)
        self._check_docstring_and_length(node, kind="function")
        self.function_stack.append((node, is_async))
        saved_loop, saved_block, saved_transaction = self.loop_depth, self.block_depth, self.transaction_depth
        self.loop_depth = 0
        self.block_depth = 0
        # A nested definition runs later, outside the enclosing transaction, unless it opens its own.
        self.transaction_depth = 1 if any(_is_transaction_context(decorator) for decorator in node.decorator_list) else 0
        self.generic_visit(node)
        self.loop_depth, self.block_depth, self.transaction_depth = saved_loop, saved_block, saved_transaction
        self.function_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        saved_transaction, self.transaction_depth = self.transaction_depth, 0
        self.generic_visit(node)
        self.transaction_depth = saved_transaction

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not re.match(r"^_?[A-Z][A-Za-z0-9]*$", node.name):
            self.add(node, "PY-NAMING-CLASS", "low", f"class `{node.name}` is not CapWords",
                     "Use domain nouns in PascalCase, e.g. InvoicePaymentService (CODE-001).")
        self._check_docstring_and_length(node, kind="class")
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def _check_defaults(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for default in [*node.args.defaults, *[item for item in node.args.kw_defaults if item is not None]]:
            mutable_literal = isinstance(default, (ast.List, ast.Dict, ast.Set))
            mutable_call = isinstance(default, ast.Call) and _dotted_name(default.func) in ("list", "dict", "set", "collections.defaultdict", "defaultdict")
            if mutable_literal or mutable_call:
                self.add(default, "PY-MUTABLE-DEFAULT", "high", f"mutable default argument in `{node.name}`",
                         "Default to None and create the object inside the function (CODE-006).")

    def _check_function_name(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name = node.name
        if name in VAGUE_FUNCTION_NAMES:
            self.add(node, "PY-VAGUE-NAME", "low", f"function name `{name}` does not say what it does",
                     "Name functions with a verb + domain object, e.g. reserve_inventory (CODE-001).")
            return
        is_dunder = name.startswith("__") and name.endswith("__")
        # unittest hooks, ast visitors and http.server handlers use names fixed by their frameworks.
        framework_override = name in UNITTEST_CAMEL_NAMES or name.startswith(("test", "visit_", "depart_", "do_"))
        if not is_dunder and not framework_override and re.search(r"[A-Z]", name):
            self.add(node, "PY-NAMING-FUNCTION", "low", f"function `{name}` is not snake_case",
                     "Python naming follows PEP 8: lowercase_with_underscores (CODE-001).")

    def _check_money_arguments(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if isinstance(argument.annotation, ast.Name) and argument.annotation.id == "float" and MONEY_NAME.search(argument.arg):
                self.add(argument, "PY-FLOAT-MONEY", "medium", f"money-like parameter `{argument.arg}` typed as float",
                         "Use Decimal or integer minor units plus an explicit currency (MONEY-002).")

    def _check_docstring_and_length(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> None:
        length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
        is_public = not node.name.startswith("_")
        if kind == "function" and length > self.settings.max_function_lines:
            self.add(node, "PY-LONG-FUNCTION", "low", f"`{node.name}` is {length} lines long",
                     "Length is a review signal: split by responsibility if it does several things (CODE-003).")
        # Nested helpers and framework hooks (visit_*, do_GET) document themselves through their parent.
        is_hook = node.name.startswith(("visit_", "do_", "depart_")) or (node.name.startswith("__") and node.name.endswith("__"))
        if self.is_test or not is_public or is_hook or (kind == "function" and self.function_stack):
            return
        threshold = self.settings.doc_min_lines if kind == "function" else self.settings.doc_min_lines * 2
        if length >= threshold and ast.get_docstring(node) is None:
            self.add(node, "PY-MISSING-DOCSTRING", "low", f"public {kind} `{node.name}` ({length} lines) has no docstring",
                     "State purpose, inputs, return value, raised errors and side effects (DOC-001/DOC-002).")

    # Blocks ------------------------------------------------------------------

    def _visit_block(self, node: ast.AST, is_loop: bool) -> None:
        self.block_depth += 1
        if is_loop:
            self.loop_depth += 1
        if self.block_depth > 4 and self.function_stack:
            function_node = self.function_stack[-1][0]
            if id(function_node) not in self.nesting_reported:
                self.nesting_reported.add(id(function_node))
                self.add(node, "PY-DEEP-NESTING", "low", f"nesting depth > 4 in `{getattr(function_node, 'name', '?')}`",
                         "Use guard clauses or extract a named helper (CODE-005).")
        self.generic_visit(node)
        if is_loop:
            self.loop_depth -= 1
        self.block_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._visit_block(node, is_loop=True)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_block(node, is_loop=True)

    def visit_While(self, node: ast.While) -> None:
        self._visit_block(node, is_loop=True)

    def visit_If(self, node: ast.If) -> None:
        self._visit_block(node, is_loop=False)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        opens_transaction = any(_is_transaction_context(item.context_expr) for item in node.items)
        self.transaction_depth += opens_transaction
        self._visit_block(node, is_loop=False)
        self.transaction_depth -= opens_transaction

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_block(node, is_loop=False)

    # Statements ----------------------------------------------------------------

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.add(node, "PY-BARE-EXCEPT", "high", "bare `except:` also catches KeyboardInterrupt/SystemExit",
                     "Catch the specific exceptions this boundary can handle and keep the cause (CODE-007).")
        swallowed = all(isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and statement.value.value is Ellipsis)
                        for statement in node.body)
        if swallowed:
            if isinstance(node.type, ast.Tuple):
                caught_names = [_dotted_name(item) or "?" for item in node.type.elts]
            else:
                caught_names = [_dotted_name(node.type) or "?"] if node.type is not None else []
            narrow = bool(caught_names) and all(name in NARROW_EXCEPTIONS for name in caught_names)
            handler_lines = self.lines[node.lineno - 1:(node.end_lineno or node.lineno)]
            explained = any("#" in line for line in handler_lines)
            severity = "info" if explained and narrow else ("low" if explained else ("medium" if narrow else "high"))
            self.add(node, "PY-SWALLOWED-EXCEPTION", severity,
                     f"exception {', '.join(caught_names) or '(any)'} is ignored" + (" (reason commented)" if explained else " silently"),
                     "Handle it, log it with context, or let it propagate; if ignoring is intended, say why in a comment (CODE-007).")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if not self.is_test:
            self.add(node, "PY-ASSERT-VALIDATION", "low", "assert used outside tests",
                     "Asserts disappear under `python -O`; raise an explicit error for validation (BE-001).")
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call) and _dotted_name(node.value.func) in ("asyncio.create_task", "asyncio.ensure_future"):
            self.add(node, "PY-DROPPED-TASK", "medium", "task created without keeping a reference",
                     "Keep the task (or use asyncio.TaskGroup) so it is awaited, cancelled and not garbage-collected (PERF-002).")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_assignment(_target_names(node.targets), node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        names = _target_names([node.target])
        if isinstance(node.annotation, ast.Name) and node.annotation.id == "float":
            for name in names:
                if MONEY_NAME.search(name):
                    self.add(node, "PY-FLOAT-MONEY", "medium", f"money-like value `{name}` typed as float",
                             "Use Decimal or integer minor units plus currency (MONEY-002).")
        if node.value is not None:
            self._check_assignment(names, node.value, node)
        self.generic_visit(node)

    def _check_assignment(self, names: list[str], value: ast.AST, node: ast.AST) -> None:
        for name in names:
            if name in VAGUE_VARIABLE_NAMES:
                self.add(node, "PY-VAGUE-NAME", "low", f"variable name `{name}` hides its meaning",
                         "Name values after what they hold, with units when relevant (CODE-001).")
            if MONEY_NAME.search(name) and (
                (isinstance(value, ast.Call) and _dotted_name(value.func) == "float")
                or (isinstance(value, ast.Constant) and isinstance(value.value, float))
            ):
                self.add(node, "PY-FLOAT-MONEY", "medium", f"money-like value `{name}` stored as float",
                         "Binary floats cannot represent most decimal amounts; use Decimal or minor units (MONEY-002).")
            if SECURITY_VALUE_NAME.search(name):
                for call in ast.walk(value):
                    if isinstance(call, ast.Call) and (_dotted_name(call.func) or "").startswith("random."):
                        self.add(node, "PY-INSECURE-RANDOM", "medium", f"`{name}` generated with the random module",
                                 "Use the secrets module for tokens, codes and salts (SEC-006).")
                        break
        if not self.function_stack and not self.class_depth and isinstance(value, ast.Call):
            called = _dotted_name(value.func) or ""
            if called in ("Session", "AsyncSession", "orm.Session") or called.endswith(("SessionLocal", "sessionmaker()")):
                self.add(node, "PY-GLOBAL-SESSION", "medium", "database session created at module level",
                         "Share the engine/pool, but open one session per request/job/task (POOL-002).")

    def visit_Call(self, node: ast.Call) -> None:
        called = _dotted_name(node.func) or ""
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        if called in ("eval", "exec"):
            self.add(node, "PY-EVAL-EXEC", "high", f"`{called}()` executes dynamic code",
                     "Never evaluate data; use a parser or an explicit dispatch table (SEC-004).")
        shell_value = keywords.get("shell")
        if isinstance(shell_value, ast.Constant) and shell_value.value is True:
            self.add(node, "PY-SHELL-TRUE", "high", f"`{called or 'call'}` runs through a shell",
                     "Pass an argv list with shell=False; never interpolate input into commands (SEC-004/RUN-001).")
        if called in ("os.system", "os.popen"):
            self.add(node, "PY-OS-SYSTEM", "medium", f"`{called}` runs a shell command",
                     "Use subprocess.run([...], check=True, timeout=...) with an argv list.")
        if called == "yaml.load":
            loader = keywords.get("Loader") or (node.args[1] if len(node.args) > 1 else None)
            loader_name = _dotted_name(loader) if loader is not None else None
            if loader_name is None or not loader_name.endswith(("SafeLoader", "CSafeLoader", "BaseLoader")):
                self.add(node, "PY-UNSAFE-YAML", "high", "yaml.load without SafeLoader can construct arbitrary objects",
                         "Use yaml.safe_load (SEC-004).")
        if called in ("yaml.unsafe_load", "yaml.full_load"):
            self.add(node, "PY-UNSAFE-YAML", "high", f"`{called}` on untrusted data is unsafe", "Use yaml.safe_load (SEC-004).")
        if called in ("pickle.load", "pickle.loads", "dill.load", "dill.loads", "marshal.loads", "shelve.open"):
            self.add(node, "PY-UNSAFE-DESERIALIZE", "medium", f"`{called}` executes code embedded in the data",
                     "Only deserialize trusted data; prefer JSON with schema validation (SEC-004).")
        verify_value = keywords.get("verify")
        if isinstance(verify_value, ast.Constant) and verify_value.value is False:
            self.add(node, "PY-TLS-VERIFY-OFF", "high", "TLS certificate verification disabled",
                     "Fix the CA bundle instead of disabling verification (SEC-006, SEC-014).")
        if called == "ssl._create_unverified_context":
            self.add(node, "PY-TLS-VERIFY-OFF", "high", "unverified SSL context", "Use ssl.create_default_context() (SEC-006).")
        if called in REQUESTS_FUNCTIONS and "timeout" not in keywords:
            self.add(node, "PY-HTTP-NO-TIMEOUT", "high", f"`{called}` without timeout can hang a worker forever",
                     "Pass timeout=(connect_seconds, read_seconds) on every remote call (BE-003).")
        if called in ("urllib.request.urlopen", "urlopen") and "timeout" not in keywords and len(node.args) < 3:
            self.add(node, "PY-HTTP-NO-TIMEOUT", "medium", "urlopen without timeout", "Pass timeout= (BE-003).")
        if self.transaction_depth and called in SLOW_IN_TRANSACTION:
            self.add(node, "PY-SLOW-CALL-IN-TRANSACTION", "medium", f"`{called}` runs while the transaction holds locks and a pooled connection",
                     "Move remote calls, mail and sleeps after commit (transaction.on_commit / outbox); a slow call here makes every "
                     "request waiting on the same rows or pool time out (TX-003, TX-011).")
        if self.in_async_function and called in BLOCKING_IN_ASYNC:
            self.add(node, "PY-BLOCKING-IN-ASYNC", "high", f"blocking `{called}` inside async def stalls the event loop",
                     "Use the async client (httpx.AsyncClient, asyncio.sleep) or asyncio.to_thread (PERF/plan §17.1).")
        elif self.in_async_function and called in SUBPROCESS_BLOCKING:
            self.add(node, "PY-BLOCKING-IN-ASYNC", "medium", f"blocking `{called}` inside async def",
                     "Use asyncio.create_subprocess_exec or asyncio.to_thread.")
        attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if (attribute in SQL_SINK_ATTRIBUTES or called in SQL_TEXT_FUNCTIONS) and node.args and _is_string_building(node.args[0]):
            self.add(node, "PY-SQL-STRING-BUILD", "high", "SQL built with string formatting",
                     "Use bound parameters (`:name` / `%s` with params); allowlist dynamic identifiers (SEC-002).")
        if called == "open" and not isinstance(getattr(node, "_devskills_parent", None), ast.withitem):
            self.add(node, "PY-OPEN-NO-WITH", "medium", "file opened without a context manager",
                     "Use `with open(...)` so the handle closes on every path (BE-004/PERF-003).")
        if called in ("threading.Thread", "Thread") and self.loop_depth > 0:
            self.add(node, "PY-THREAD-IN-LOOP", "medium", "threads created inside a loop are unbounded",
                     "Use a bounded ThreadPoolExecutor and bound the queue of pending work (PERF-001).")
        if called.endswith(("ThreadPoolExecutor", "ProcessPoolExecutor")) and "max_workers" not in keywords and not node.args:
            self.add(node, "PY-EXECUTOR-NO-LIMIT", "low", f"`{called}` without max_workers",
                     "Size the pool for the workload and limit in-flight submissions (PERF-001).")
        if called in ("create_engine", "sqlalchemy.create_engine", "create_async_engine", "sqlalchemy.ext.asyncio.create_async_engine"):
            function_name = getattr(self.function_stack[-1][0], "name", "") if self.function_stack else ""
            if self.function_stack and not FACTORY_FUNCTION.match(function_name):
                self.add(node, "PY-ENGINE-PER-CALL", "medium", f"engine created inside `{function_name}`",
                         "Create the engine once per process (app startup/lifespan) and reuse its pool (POOL-001).")
        if called in ("datetime.now", "datetime.datetime.now") and not node.args and "tz" not in keywords:
            self.add(node, "PY-NAIVE-DATETIME", "low", "naive datetime.now()",
                     "Use datetime.now(timezone.utc) or an explicit business time zone (API-009).")
        if called in ("datetime.utcnow", "datetime.datetime.utcnow"):
            self.add(node, "PY-NAIVE-DATETIME", "low", "datetime.utcnow() returns a naive value (deprecated in 3.12)",
                     "Use datetime.now(timezone.utc) (API-009).")
        self.generic_visit(node)


def _python_comment_findings(rel_path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return findings
    for token in tokens:
        if token.type == tokenize.COMMENT and TODO_PATTERN.search(token.string) and not TODO_HAS_OWNER.search(token.string):
            findings.append(_finding("PY-TODO-NO-OWNER", "low", "TODO/FIXME without owner or issue", rel_path, token.start[0],
                                     "Write `TODO(owner): reason` or link an issue (DOC-004)."))
    return findings


def _python_string_statements(rel_path: str, tree: ast.AST) -> list[Finding]:
    """Bare string statements outside docstring positions are not comments (plan §9.2)."""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            is_string = isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
            if not is_string or index == 0:
                continue
            previous = body[index - 1]
            if isinstance(previous, (ast.Assign, ast.AnnAssign)) and isinstance(node, (ast.Module, ast.ClassDef)):
                continue  # Module/class attribute docstrings (a Sphinx convention) are allowed.
            findings.append(_finding("PY-STRING-AS-COMMENT", "low", "string literal used as a block comment", rel_path,
                                     statement.lineno, "Use # lines for comments; docstrings belong only at the top of a module/class/function (DOC-005)."))
    return findings


def check_python(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Analyse one Python file with ast (style, resources, safety, security); unparseable files report a syntax error."""
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        findings = [_finding("PY-SYNTAX-ERROR", "high", f"file does not parse: {error.msg}", rel_path, error.lineno)]
        for line_number, line in enumerate(text.splitlines(), start=1):
            if re.match(r"^\s*(/\*|\*/|//)", line):
                findings.append(_finding("PY-C-STYLE-COMMENT", "high", "C-style comment in Python", rel_path, line_number,
                                         "Python comments use #; documentation uses docstrings (DOC-005)."))
        return findings
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._devskills_parent = parent  # type: ignore[attr-defined]
    visitor = _PythonVisitor(rel_path, settings, is_test_path(rel_path), text.splitlines())
    visitor.visit(tree)
    return (visitor.findings + _python_comment_findings(rel_path, text) + _python_string_statements(rel_path, tree)
            + python_security_findings(rel_path, tree, text))


# --------------------------------------------------------------------------- C-like masking


@dataclass
class Comment:
    start_line: int
    end_line: int
    kind: str  # "line" or "block"
    text: str
    standalone: bool  # True when nothing but whitespace precedes it on its line


def mask_c_like(text: str, *, hash_comments: bool = False, backtick_strings: bool = True) -> tuple[str, str, list[Comment]]:
    """Mask a C-like source file.

    Returns (code_without_comments, code_without_comments_and_strings, comments).
    Every newline is preserved so line numbers stay valid. Single/double-quoted
    strings end at a newline, which limits damage from apostrophes in JSX text.
    """
    no_comments: list[str] = []
    masked: list[str] = []
    comments: list[Comment] = []
    index = 0
    length = len(text)
    line = 1
    line_has_code = False
    last_significant = ""

    def emit(char: str, keep_in_masked: bool, keep_in_no_comments: bool = True) -> None:
        no_comments.append(char if keep_in_no_comments or char == "\n" else " ")
        masked.append(char if keep_in_masked or char == "\n" else " ")

    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""
        if char == "\n":
            emit(char, True)
            line += 1
            line_has_code = False
            index += 1
            continue
        if char == "/" and next_char == "/" or (hash_comments and char == "#" and next_char != "["):
            end = text.find("\n", index)
            end = length if end == -1 else end
            comments.append(Comment(line, line, "line", text[index:end], not line_has_code))
            for comment_char in text[index:end]:
                emit(comment_char, False, False)
            index = end
            continue
        if char == "/" and next_char == "*":
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            body = text[index:end]
            comments.append(Comment(line, line + body.count("\n"), "block", body, not line_has_code))
            for comment_char in body:
                emit(comment_char, False, False)
                if comment_char == "\n":
                    line += 1
            index = end
            continue
        if char in "'\"" or (char == "`" and backtick_strings):
            quote = char
            emit(char, True)
            index += 1
            while index < length:
                current = text[index]
                if current == "\\" and index + 1 < length:
                    emit(current, False)
                    emit(text[index + 1], False)
                    if text[index + 1] == "\n":
                        line += 1
                    index += 2
                    continue
                if current == "\n" and quote != "`":
                    break
                if current == quote:
                    emit(current, True)
                    index += 1
                    break
                if quote == "`" and current == "$" and index + 1 < length and text[index + 1] == "{":
                    # Template expression: code until the matching brace, then back to the string.
                    emit("$", True)
                    emit("{", True)
                    index += 2
                    depth = 1
                    while index < length and depth:
                        inner = text[index]
                        if inner == "{":
                            depth += 1
                        elif inner == "}":
                            depth -= 1
                        emit(inner, True)
                        if inner == "\n":
                            line += 1
                        index += 1
                    continue
                emit(current, False)
                if current == "\n":
                    line += 1
                index += 1
            line_has_code = True
            last_significant = quote
            continue
        if char == "/" and (last_significant in "(,=:[!&|?{};+-*%<>~^" or last_significant == ""):
            # Regex literal: skip to the closing slash outside character classes.
            emit(char, True)
            index += 1
            in_class = False
            while index < length and text[index] != "\n":
                current = text[index]
                if current == "\\":
                    emit(current, False)
                    if index + 1 < length:
                        emit(text[index + 1], False)
                    index += 2
                    continue
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    emit(current, True)
                    index += 1
                    break
                emit(current, False)
                index += 1
            line_has_code = True
            last_significant = "/"
            continue
        if not char.isspace():
            line_has_code = True
            last_significant = char
        emit(char, True)
        index += 1
    return "".join(no_comments), "".join(masked), comments


def _matching_brace(masked: str, open_index: int) -> int:
    """Index of the brace closing the one at `open_index` in masked code (strings/comments blanked)."""
    depth = 0
    for index in range(open_index, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(masked) - 1


def _comment_style_findings(rel_path: str, comments: list[Comment], settings: CheckSettings, rule_prefix: str, line_marker: str) -> list[Finding]:
    """Enforce the project's multi-line comment style and flag commented-out code (DOC-003, DOC-005)."""
    findings: list[Finding] = []
    if settings.multiline_comment_style == "off":
        return findings
    if settings.multiline_comment_style == "line":
        for comment in comments:
            if comment.kind == "block" and comment.end_line > comment.start_line and not comment.text.startswith("/**"):
                findings.append(_finding(f"{rule_prefix}-COMMENT-STYLE", "low", "multi-line /* */ comment; project style is line comments",
                                         rel_path, comment.start_line))
        return findings
    run: list[Comment] = []

    def flush() -> None:
        if len(run) >= 3:
            code_like = sum(1 for item in run if CODE_LIKE_COMMENT.match(item.text))
            if code_like * 2 >= len(run):
                findings.append(_finding("GEN-COMMENTED-OUT-CODE", "low", f"{len(run)} lines of commented-out code", rel_path,
                                         run[0].start_line, "Delete it; version control keeps history (DOC-003)."))
            else:
                findings.append(_finding(f"{rule_prefix}-MULTILINE-COMMENT", "low",
                                         f"{len(run)} consecutive {line_marker} lines form a multi-line comment", rel_path,
                                         run[0].start_line,
                                         "Project style: multi-line comments use /* ... */ (or /** ... */ for API docs) (DOC-005)."))
        run.clear()

    for comment in comments:
        eligible = (comment.kind == "line" and comment.standalone and not comment.text.startswith("///")
                    and not DIRECTIVE_COMMENT.match(comment.text))
        if eligible and run and comment.start_line == run[-1].start_line + 1:
            run.append(comment)
            continue
        flush()
        if eligible:
            run.append(comment)
    flush()
    return findings


def _todo_findings(rel_path: str, comments: list[Comment], rule_prefix: str) -> list[Finding]:
    return [
        _finding(f"{rule_prefix}-TODO-NO-OWNER", "low", "TODO/FIXME without owner or issue", rel_path, comment.start_line,
                 "Write `TODO(owner): reason` or link an issue (DOC-004).")
        for comment in comments
        if TODO_PATTERN.search(comment.text) and not TODO_HAS_OWNER.search(comment.text)
    ]


SQL_KEYWORDS_START = r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|REPLACE\s+INTO)\b"
SQL_CONCAT_PATTERNS = (
    re.compile(r"(['\"])\s*" + SQL_KEYWORDS_START + r"[^'\"\n]*\1\s*\+\s*[A-Za-z_$]", re.IGNORECASE),
    re.compile(r"(['\"])[^'\"\n]*\b(?:WHERE|AND|OR|SET|VALUES)\b[^'\"\n]*[=(]\s*['\"]?\1\s*\+\s*[A-Za-z_$]", re.IGNORECASE),
    re.compile(r"(?<![\w$.])`\s*" + SQL_KEYWORDS_START + r"[^`]*\$\{", re.IGNORECASE),
    re.compile(r"(?:Sprintf|String\.format|sprintf|format)\(\s*\"\s*" + SQL_KEYWORDS_START + r"[^\"]*%[sdv]", re.IGNORECASE),
)


def _sql_concat_findings(rel_path: str, code_no_comments: str, prefix: str) -> list[Finding]:
    findings = []
    for pattern in SQL_CONCAT_PATTERNS:
        for match in pattern.finditer(code_no_comments):
            findings.append(_finding(f"{prefix}-SQL-STRING-BUILD", "high", "SQL text built from variables", rel_path,
                                     _line_of(code_no_comments, match.start()),
                                     "Use bound parameters / the ORM query builder; allowlist dynamic identifiers (SEC-002)."))
    return findings


def _empty_catch_findings(rel_path: str, masked: str, raw: str, prefix: str) -> list[Finding]:
    findings = []
    for match in re.finditer(r"\bcatch\s*(\([^)]*\))?\s*\{\s*\}", masked):
        commented = "//" in raw[match.start():match.end()] or "/*" in raw[match.start():match.end()]
        findings.append(_finding(f"{prefix}-EMPTY-CATCH", "medium" if commented else "high", "exception swallowed by an empty catch",
                                 rel_path, _line_of(masked, match.start()),
                                 "Handle, log with context, or rethrow; never return success after an error (CODE-007)."))
    return findings


def check_javascript(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Check JS/TS with strings/comments masked: XSS sinks, eval, SQL building, effect cleanup, docs, comment style."""
    no_comments, masked, comments = mask_c_like(text)
    suffix = PurePosixPath(rel_path).suffix.lower()
    is_test = is_test_path(rel_path)
    findings: list[Finding] = []

    def add(rule_id: str, severity: str, message: str, offset: int, hint: str | None = None, source: str = masked) -> None:
        findings.append(_finding(rule_id, severity, message, rel_path, _line_of(source, offset), hint))

    for match in re.finditer(r"(?<![\w$.])eval\s*\(|\bnew\s+Function\s*\(", masked):
        add("JS-EVAL", "high", "dynamic code execution", match.start(), "Remove eval/new Function; parse data explicitly (SEC-004).")
    for match in re.finditer(r"dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML\s*\(|bypassSecurityTrust\w*\(", masked):
        add("JS-UNSAFE-HTML", "medium", "raw HTML injection point", match.start(),
            "Render text by default; sanitize with a maintained sanitizer when HTML is required (FE-009).")
    for match in re.finditer(r"(?<![\w$.])debugger\s*;?", masked):
        add("JS-DEBUGGER", "medium", "debugger statement left in code", match.start())
    if not is_test:
        for match in re.finditer(r"\bconsole\.(log|debug)\s*\(", masked):
            add("JS-CONSOLE-LOG", "low", "console.log left in non-test code", match.start(),
                "Use the project's logger with redaction, or remove it (SEC-010).")
    if suffix in (".ts", ".tsx"):
        for match in re.finditer(r":\s*any\b(?!\w)|\bas\s+any\b|<any>", masked):
            add("TS-ANY", "low", "`any` disables type checking here", match.start(),
                "Use a precise type or `unknown` plus validation at the boundary (CODE-002).")
    for match in re.finditer(r"localStorage\.setItem\(\s*['\"`][^'\"`]*(token|jwt|auth|session)", no_comments, re.IGNORECASE):
        add("JS-TOKEN-IN-STORAGE", "medium", "auth token stored in localStorage", match.start(),
            "Readable by any XSS; prefer httpOnly cookies or the framework's session mechanism (SEC-007).", no_comments)
    for match in re.finditer(r"parseFloat\([^)]*(amount|price|total|balance|fee|cost)", no_comments, re.IGNORECASE):
        add("JS-FLOAT-MONEY", "low", "money parsed as binary float", match.start(),
            "Use integer minor units or a decimal library and keep currency explicit (MONEY-002).", no_comments)
    findings += _sql_concat_findings(rel_path, no_comments, "JS")
    findings += _empty_catch_findings(rel_path, masked, text, "JS")
    findings += _effect_cleanup_findings(rel_path, masked)
    findings += pattern_findings("js", rel_path, masked, no_comments)

    if suffix in (".ts", ".js", ".mjs", ".cjs") and not is_test:
        raw_lines = text.splitlines()
        for match in re.finditer(r"^[ \t]*export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|"
                                 r"^[ \t]*export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:async\s*)?\(", masked, re.MULTILINE):
            line_number = _line_of(masked, match.start())
            previous = next((raw_lines[index].strip() for index in range(line_number - 2, -1, -1) if raw_lines[index].strip()), "")
            if previous.endswith("*/"):
                continue
            brace = masked.find("{", match.end())
            body_lines = masked.count("\n", match.start(), _matching_brace(masked, brace)) + 1 if brace != -1 else 1
            if body_lines >= settings.doc_min_lines:
                name = match.group(1) or match.group(2)
                add("JS-EXPORT-NO-DOC", "low", f"exported function `{name}` ({body_lines} lines) has no doc comment", match.start(),
                    "Add /** purpose, @param, @returns, @throws */ (DOC-001/DOC-002).")
    findings += _comment_style_findings(rel_path, comments, settings, "JS", "//")
    findings += _todo_findings(rel_path, comments, "JS")
    return findings


def _effect_cleanup_findings(rel_path: str, masked: str) -> list[Finding]:
    """React effects that subscribe or schedule work must return a cleanup function (FE-002)."""
    findings = []
    for match in re.finditer(r"\buse(Layout)?Effect\s*\(", masked):
        arrow = masked.find("=>", match.end())
        brace = masked.find("{", arrow if arrow != -1 else match.end())
        if arrow == -1 or brace == -1 or brace - arrow > 5:
            continue
        end = _matching_brace(masked, brace)
        body = masked[brace:end]
        subscribes = re.search(r"addEventListener|setInterval|setTimeout|\.subscribe\(|new\s+WebSocket|new\s+EventSource|\.observe\(|\.on\(", body)
        if subscribes and not re.search(r"\breturn\b", body):
            findings.append(_finding("JS-EFFECT-NO-CLEANUP", "medium", "effect subscribes/schedules work without cleanup",
                                     rel_path, _line_of(masked, match.start()),
                                     "Return a cleanup that removes listeners, clears timers and aborts requests (FE-002)."))
    return findings


def check_single_file_component(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Vue/Svelte: JS checks inside <script>, template checks for raw HTML bindings."""
    findings: list[Finding] = []
    for match in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.DOTALL | re.IGNORECASE):
        offset_line = _line_of(text, match.start(1)) - 1
        for finding in check_javascript(rel_path + ".ts", match.group(1), settings):
            finding.path = rel_path
            finding.line = (finding.line or 0) + offset_line
            findings.append(finding)
    for match in re.finditer(r"\sv-html\s*=|\{@html\s", text):
        findings.append(_finding("SFC-UNSAFE-HTML", "medium", "raw HTML binding in template", rel_path, _line_of(text, match.start()),
                                 "Bind text instead, or sanitize before rendering (FE-009)."))
    if rel_path.endswith(".vue") and re.search(r"onMounted\s*\(", text) and re.search(r"addEventListener|setInterval", text) \
            and not re.search(r"onUnmounted|onBeforeUnmount|removeEventListener|clearInterval", text):
        findings.append(_finding("VUE-NO-UNMOUNT-CLEANUP", "medium", "listener/timer registered without unmount cleanup", rel_path,
                                 _line_of(text, text.find("onMounted")), "Remove listeners and timers in onBeforeUnmount (FE-002)."))
    return findings


def check_php(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Check PHP: eval/shell, raw SQL, superglobals, debug output, XSS/LFI/SSRF patterns and comment style."""
    no_comments, masked, comments = mask_c_like(text, hash_comments=True, backtick_strings=False)
    is_test = is_test_path(rel_path)
    findings: list[Finding] = []

    def add(rule_id: str, severity: str, message: str, offset: int, hint: str | None = None, source: str = masked) -> None:
        findings.append(_finding(rule_id, severity, message, rel_path, _line_of(source, offset), hint))

    for match in re.finditer(r"(?<![\w>:$])eval\s*\(", masked):
        add("PHP-EVAL", "high", "eval() executes dynamic code", match.start(), "Remove eval (SEC-004).")
    for match in re.finditer(r"(?<![\w>:$])(exec|shell_exec|system|passthru|proc_open|popen)\s*\([^)]*\$", no_comments):
        add("PHP-SHELL", "high", f"{match.group(1)}() with variable input", match.start(),
            "Avoid shell calls; if required, use escapeshellarg on each argument (SEC-004).", no_comments)
    for match in re.finditer(r"\bunserialize\s*\(", masked):
        add("PHP-UNSERIALIZE", "medium", "unserialize() can instantiate objects from data", match.start(),
            "Use json_decode for untrusted data, or allowed_classes => false (SEC-004).")
    for match in re.finditer(r"(?:->|::)(?:whereRaw|selectRaw|orderByRaw|havingRaw|raw|select|statement|unprepared)\s*\(\s*\"[^\"]*\$|"
                             r"(?:->|::)(?:whereRaw|selectRaw|orderByRaw|havingRaw|raw|statement|unprepared)\s*\([^)]*['\"]\s*\.\s*\$|"
                             r"mysqli?_query\s*\([^)]*\.\s*\$", no_comments):
        add("PHP-SQL-STRING-BUILD", "high", "raw SQL built from variables", match.start(),
            "Use bindings: whereRaw('col = ?', [$value]) or the query builder (SEC-002).", no_comments)
    for match in re.finditer(r"\$_(GET|POST|REQUEST|COOKIE)\s*\[", masked):
        add("PHP-RAW-SUPERGLOBAL", "low", f"direct ${'_' + match.group(1)} access", match.start(),
            "Validate input at the boundary, e.g. $request->validate() in Laravel (BE-001).")
    if not is_test:
        for match in re.finditer(r"(?<![\w>:$])(dd|dump|var_dump|print_r)\s*\(", masked):
            add("PHP-DEBUG-OUTPUT", "low", f"{match.group(1)}() left in code", match.start())
    for match in re.finditer(r"DB::transaction\s*\(\s*(?:static\s+)?function\b[^{]*\{", masked):
        body_start = match.end() - 1
        body = masked[body_start:_matching_brace(masked, body_start) + 1]
        for slow in re.finditer(r"\b(Http|Mail|Notification)::\w+|(?<![\w>:$])(sleep|usleep|curl_exec|file_get_contents)\s*\(", body):
            add("PHP-SLOW-CALL-IN-TRANSACTION", "medium", f"{slow.group(0).rstrip('(').strip()} runs inside DB::transaction", body_start + slow.start(),
                "Dispatch it after commit (afterCommit jobs, DB::afterCommit, outbox): a slow call holds locks and the connection, "
                "and requests waiting on the same rows time out (TX-003, TX-011).")
    findings += _sql_concat_findings(rel_path, no_comments, "PHP")
    findings += _empty_catch_findings(rel_path, masked, text, "PHP")
    findings += pattern_findings("php", rel_path, masked, no_comments)
    findings += _comment_style_findings(rel_path, comments, settings, "PHP", "//")
    findings += _todo_findings(rel_path, comments, "PHP")
    return findings


def check_c_like(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Check Java/Kotlin/C#/C-family: empty catch, SQL concatenation, unbounded pools, @Transactional misuse."""
    no_comments, masked, comments = mask_c_like(text, backtick_strings=False)
    suffix = PurePosixPath(rel_path).suffix.lower()
    is_test = is_test_path(rel_path)
    findings: list[Finding] = []
    prefix = {".java": "JAVA", ".kt": "KT", ".kts": "KT", ".cs": "CS"}.get(suffix, "CLIKE")
    for match in re.finditer(r"\.printStackTrace\s*\(\s*\)", masked):
        findings.append(_finding(f"{prefix}-PRINT-STACKTRACE", "low", "printStackTrace() bypasses structured logging", rel_path,
                                 _line_of(masked, match.start()), "Log with the project logger and context (plan §23.1)."))
    if not is_test:
        for match in re.finditer(r"System\.out\.println|Console\.WriteLine", masked):
            findings.append(_finding(f"{prefix}-CONSOLE-OUTPUT", "low", "console output in non-test code", rel_path,
                                     _line_of(masked, match.start())))
    for match in re.finditer(r"Executors\.newCachedThreadPool\s*\(", masked):
        findings.append(_finding(f"{prefix}-UNBOUNDED-POOL", "medium", "cached thread pool grows without limit", rel_path,
                                 _line_of(masked, match.start()), "Use a bounded ThreadPoolExecutor with a bounded queue (PERF-001)."))
    for match in re.finditer(r"@Transactional[^\n]*\n\s*(?:@\w+[^\n]*\n\s*)*private\s", masked):
        findings.append(_finding("JAVA-TX-PRIVATE", "medium", "@Transactional on a private method is ignored by Spring proxies",
                                 rel_path, _line_of(masked, match.start()), "Put the transaction boundary on a public use-case method (TX-001)."))
    findings += _sql_concat_findings(rel_path, no_comments, prefix)
    findings += _empty_catch_findings(rel_path, masked, text, prefix)
    findings += _comment_style_findings(rel_path, comments, settings, prefix, "//")
    findings += _todo_findings(rel_path, comments, prefix)
    language = {".java": "java", ".kt": "java", ".kts": "java", ".cs": "cs"}.get(suffix)
    if language:
        findings += pattern_findings(language, rel_path, masked, no_comments)
    return findings


def check_go(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Check Go: HTTP clients without timeout, goroutines/defer inside loops, SQL built with Sprintf."""
    no_comments, masked, comments = mask_c_like(text, backtick_strings=True)
    findings: list[Finding] = []
    for match in re.finditer(r"\bhttp\.(Get|Post|PostForm|Head)\s*\(|&http\.Client\{\s*\}", masked):
        findings.append(_finding("GO-HTTP-NO-TIMEOUT", "medium", "default HTTP client has no timeout", rel_path,
                                 _line_of(masked, match.start()), "Use an http.Client with Timeout or a context deadline (BE-003)."))
    for loop in re.finditer(r"\bfor\b[^{\n]*\{", masked):
        end = _matching_brace(masked, loop.end() - 1)
        body = masked[loop.end():end]
        if re.search(r"\bgo\s+(func\b|\w+\()", body):
            findings.append(_finding("GO-GOROUTINE-IN-LOOP", "medium", "goroutine started per loop iteration", rel_path,
                                     _line_of(masked, loop.start()), "Bound concurrency with a worker pool or semaphore (PERF-001)."))
        if re.search(r"\bdefer\b", body):
            findings.append(_finding("GO-DEFER-IN-LOOP", "low", "defer inside a loop runs only when the function returns", rel_path,
                                     _line_of(masked, loop.start()), "Close resources inside the iteration (PERF-003)."))
    findings += _sql_concat_findings(rel_path, no_comments, "GO")
    # Go convention is // for every comment, so only TODO ownership is checked.
    findings += _todo_findings(rel_path, comments, "GO")
    return findings


def check_ruby(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    findings = check_hash_comment_file(rel_path, text)
    for match in re.finditer(r"(find_by_sql|where|execute|select_all|exec_query|order)\s*\(?\s*\"[^\"]*#\{", text):
        findings.append(_finding("RUBY-SQL-INTERPOLATION", "high", "SQL string interpolation", rel_path, _line_of(text, match.start()),
                                 "Use placeholders: where('id = ?', id) (SEC-002)."))
    return findings


def check_hash_comment_file(rel_path: str, text: str) -> list[Finding]:
    """YAML/TOML/shell/Ruby use #; C-style comment lines there are syntax errors (DOC-005)."""
    findings = []
    in_block_scalar_indent: int | None = None
    is_yaml = rel_path.endswith((".yml", ".yaml"))
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if is_yaml:
            if in_block_scalar_indent is not None and (not stripped or indent > in_block_scalar_indent):
                continue
            in_block_scalar_indent = indent if re.search(r":\s*[|>][-+]?\s*$", line) else None
        if re.match(r"(/\*|\*/|//)", stripped):
            findings.append(_finding("CFG-C-STYLE-COMMENT", "high", "C-style comment in a #-comment language", rel_path, line_number,
                                     "Use # for comments in this file type (DOC-005)."))
        comment = line.split("#", 1)[1] if "#" in line else ""
        if comment and TODO_PATTERN.match(comment) and not TODO_HAS_OWNER.search(comment):
            findings.append(_finding("CFG-TODO-NO-OWNER", "low", "TODO/FIXME without owner or issue", rel_path, line_number))
    return findings


def check_merge_markers(rel_path: str, text: str) -> list[Finding]:
    findings = []
    for match in re.finditer(r"^(<{7} |>{7} |\|{7} )", text, re.MULTILINE):
        findings.append(_finding("GEN-MERGE-CONFLICT", "critical", "unresolved merge conflict marker", rel_path, _line_of(text, match.start())))
    return findings


def _apply_suppressions(findings: list[Finding], text: str) -> tuple[list[Finding], list[Finding]]:
    """Honor `devskills:ignore RULE reason` on the same line, or on a comment-only line just above.

    Reasons are mandatory; an inline suppression at the end of a code line covers only that line.
    """
    lines = text.splitlines()
    suppressions: dict[int, tuple[set[str], str, bool]] = {}
    for line_number, line in enumerate(lines, start=1):
        match = SUPPRESSION.search(line)
        if match and match.group(2).strip(" -:*/#>"):
            rule_ids = {rule.strip() for rule in re.split(r"[ ,]+", match.group(1)) if rule.strip()}
            comment_only = line.lstrip().startswith(("#", "//", "/*", "*", "--", "<!--"))
            suppressions[line_number] = (rule_ids, match.group(2).strip(" -:*/#>"), comment_only)
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for finding in findings:
        reason = None
        same_line = suppressions.get(finding.line or -1)
        line_above = suppressions.get((finding.line or 0) - 1)
        if same_line and finding.rule_id in same_line[0]:
            reason = same_line[1]
        elif line_above and line_above[2] and finding.rule_id in line_above[0]:
            reason = line_above[1]
        if reason:
            finding.hint = f"suppressed: {reason}"
            suppressed.append(finding)
        else:
            kept.append(finding)
    return kept, suppressed


def check_file(rel_path: str, text: str, settings: CheckSettings) -> list[Finding]:
    """Dispatch one file to its language checker; merge-conflict markers are checked for every file."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    findings = check_merge_markers(rel_path, text)
    if suffix in PY_SUFFIXES:
        findings += check_python(rel_path, text, settings)
    elif suffix in JS_SUFFIXES:
        findings += check_javascript(rel_path, text, settings)
    elif suffix in SFC_SUFFIXES:
        findings += check_single_file_component(rel_path, text, settings)
    elif suffix in PHP_SUFFIXES:
        findings += check_php(rel_path, text, settings)
    elif suffix in C_LIKE_SUFFIXES:
        findings += check_c_like(rel_path, text, settings)
    elif suffix in GO_SUFFIXES:
        findings += check_go(rel_path, text, settings)
    elif suffix in RUBY_SUFFIXES:
        findings += check_ruby(rel_path, text, settings)
    elif suffix in HASH_COMMENT_SUFFIXES:
        findings += check_hash_comment_file(rel_path, text)
    return findings


def run(args: argparse.Namespace) -> int:
    """CLI handler for `check-code`: select files, run checkers, apply suppressions, record the gate."""
    repo_root = resolve_repo_root(args.repo)
    profile, profile_warnings = load_profile(repo_root)
    started_at = utc_now_iso()
    code_profile = profile["code"]
    settings = CheckSettings(
        multiline_comment_style=code_profile["multiline_comment_style"],
        max_function_lines=code_profile["max_function_lines"],
        doc_min_lines=code_profile["doc_min_lines"],
        hardcoded_values=code_profile["hardcoded_values"],
    )
    fail_on = args.fail_on or code_profile["fail_on"]
    scope = "paths" if args.paths else ("all" if args.all else "changed")
    targets = [path for path in select_target_files(repo_root, args.paths, scope, args.base)
               if PurePosixPath(path).suffix.lower() in SUPPORTED_SUFFIXES and not is_secret_file(path) and not is_lockfile(path)
               and not path.endswith((".min.js", ".d.ts"))]

    # Enums/constants the whole repo defines, so a changed file can be told which literal it duplicates (CODE-011).
    value_sets = index_repository(repo_root) if settings.hardcoded_values and targets else []
    findings: list[Finding] = []
    suppressed: list[Finding] = []
    checked = 0
    for rel_path in targets:
        text = read_text_limited(repo_root / rel_path)
        if text is None:
            continue
        checked += 1
        file_findings = check_file(rel_path, text, settings) + hardcoded_value_findings(rel_path, text, value_sets)
        kept, file_suppressed = _apply_suppressions(file_findings, text)
        findings.extend(kept)
        suppressed.extend(file_suppressed)

    gate = gate_from_findings(findings, fail_on)
    details: dict[str, Any] = {
        "scope": scope,
        "files_checked": checked,
        "fail_on": fail_on,
        "settings": settings.__dict__,
        "domain_value_sets": len(value_sets),
        "suppressed": [finding.to_dict() for finding in suppressed],
        "profile_warnings": profile_warnings,
        "note": "Signals for review; naming/comment quality still needs semantic review (plan §25.4).",
    }
    result = CheckResult(
        check_id=getattr(args, "check_id", "code.static"),
        tool="devskills.check-code",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="findings" if findings else "clean",
        summary=f"{checked} files ({scope}); {severity_summary(findings)}; {len(suppressed)} suppressed",
        findings=findings,
        details=details,
        started_at=started_at,
    )
    lines = [f"check-code: {result.summary}"]
    lines.extend(format_findings(findings))
    for warning in profile_warnings:
        lines.append(f"  profile warning: {warning}")
    if not targets:
        lines.append("  no supported changed files; use --paths or --all to choose files explicitly")
    return emit_result(args, repo_root, result, lines)
