"""Static checks for SQL migrations, schema changes and ORM foreign keys (plan §14-§16).

The SQL scanner masks comments and string literals, splits statements and
applies rules for destructive changes, missing primary keys, money stored as
floats, risky index builds and the project's foreign-key policy. ORM code is
checked for foreign keys created implicitly (Django ForeignKey, Laravel
constrained(), Prisma relations, TypeORM relations, ...), with a hint on how
each ORM keeps the relation without a database constraint.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from devskills.fsutil import read_text_limited, resolve_repo_root, select_target_files, utc_now_iso
from devskills.models import EXEC_COMPLETED, CheckResult, Finding, gate_from_findings
from devskills.output import emit_result, format_findings, severity_summary
from devskills.profile import load_profile

MONEY_COLUMN = re.compile(r"(?i)(amount|price|balance|fee|cost|tax|discount|refund|salary|total|subtotal|money)"
                          r"(?!\w*(rate|ratio|percent|pct|count|_id)\b)")
FLOAT_TYPE = re.compile(r"(?i)\b(float\d*|real|double(\s+precision)?)\b")
CREATED_AT_COLUMN = re.compile(r"(?i)^[`\"\[]?(created_at|created_on|inserted_at|createdat|create_time|date_created)[`\"\]]?$")
SNAKE_CASE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
KEY_COLUMN = re.compile(r"(?i)^(id|\w+_id)$")
KEY_CONSTRAINT_ADD = re.compile(r"(?i)^ADD\s+(?:CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|UNIQUE)\b")
TYPE_CHANGE = re.compile(r"(?i)^(?:ALTER\s+(?:COLUMN\s+)?([\w\"`\[\]]+)\s+(?:SET\s+DATA\s+)?TYPE\b|MODIFY\s+(?:COLUMN\s+)?([\w\"`\[\]]+)|CHANGE\s+(?:COLUMN\s+)?([\w\"`\[\]]+))")
LOCK_TIMEOUT_SETTING = re.compile(r"(?i)^SET\s+(?:LOCAL\s+|SESSION\s+|@@SESSION\.)?(?:INNODB_)?LOCK(?:_WAIT)?_TIMEOUT\b")
MIGRATION_PATH = re.compile(r"(?i)(^|/)(migrations?|alembic|db/migrate|database/migrations|flyway|liquibase|changelog)(/|$)")

ORM_SUFFIXES = frozenset({".py", ".php", ".ts", ".js", ".prisma", ".rb", ".java", ".kt", ".cs"})
# ORM relations live in model/entity/migration/schema files; scanning other code only adds noise.
ORM_MODEL_PATH = re.compile(
    r"(?i)(^|/)(models?|entit(y|ies)|domain|schemas?|migrations?|migrate|alembic|database|db)(/|_|\.|$)|"
    r"models?\.py$|\.entity\.(ts|js)$|Entity\.(java|kt|cs)$|(Db)?Context\.cs$"
)


@dataclass(frozen=True)
class OrmForeignKeyPattern:
    orm: str
    suffixes: frozenset[str]
    regex: re.Pattern[str]
    hint: str
    # Text that, when present on the same statement line, means the DB constraint is disabled.
    disabled_marker: re.Pattern[str] | None = None


ORM_FOREIGN_KEY_PATTERNS: tuple[OrmForeignKeyPattern, ...] = (
    OrmForeignKeyPattern("Django", frozenset({".py"}), re.compile(r"models\.(ForeignKey|OneToOneField)\s*\("),
                         "Keep the ORM relation without a DB constraint via db_constraint=False and document on_delete policy.",
                         re.compile(r"db_constraint\s*=\s*False")),
    OrmForeignKeyPattern("SQLAlchemy/Alembic", frozenset({".py"}),
                         re.compile(r"(?<!models\.)\bForeignKey\s*\(|ForeignKeyConstraint\s*\(|op\.create_foreign_key\s*\("),
                         "relationship() works without a DB FK: use primaryjoin with foreign() and add an index on the column."),
    OrmForeignKeyPattern("Laravel", frozenset({".php"}), re.compile(r"->constrained\s*\(|->foreign\s*\(|->foreignIdFor\s*\([^)]*\)\s*->constrained"),
                         "Use foreignId('x')->index() (or unsignedBigInteger) without constrained(); enforce integrity in the owning service."),
    OrmForeignKeyPattern("Prisma", frozenset({".prisma"}), re.compile(r"@relation\s*\("),
                         "Set relationMode = \"prisma\" in the datasource to skip DB FKs, and add @@index on the relation scalar.",
                         re.compile(r"relationMode\s*=\s*\"prisma\"")),
    OrmForeignKeyPattern("TypeORM", frozenset({".ts", ".js"}), re.compile(r"@(ManyToOne|OneToOne)\s*\("),
                         "Pass { createForeignKeyConstraints: false } and index the join column.",
                         re.compile(r"createForeignKeyConstraints\s*:\s*false")),
    OrmForeignKeyPattern("Sequelize", frozenset({".ts", ".js"}), re.compile(r"\.(belongsTo|hasMany|hasOne)\s*\("),
                         "Pass { constraints: false } to keep associations without DB FKs.",
                         re.compile(r"constraints\s*:\s*false")),
    OrmForeignKeyPattern("Rails", frozenset({".rb"}), re.compile(r"add_foreign_key\b|foreign_key:\s*true"),
                         "Use t.references ... index: true without foreign_key: true; validate in the model/service."),
    OrmForeignKeyPattern("JPA/Hibernate", frozenset({".java", ".kt"}), re.compile(r"@(ManyToOne|OneToOne)\b"),
                         "Use @JoinColumn(foreignKey = @ForeignKey(ConstraintMode.NO_CONSTRAINT)) and index the column.",
                         re.compile(r"ConstraintMode\.NO_CONSTRAINT")),
    OrmForeignKeyPattern("EF Core", frozenset({".cs"}), re.compile(r"\.HasForeignKey\s*\(|\.HasOne\s*\(|\[ForeignKey\("),
                         "EF Core creates FK constraints for navigations by convention; review the generated migration."),
)


@dataclass(frozen=True)
class SqlStatement:
    start_line: int
    text: str  # comments and string literals masked, original case


def mask_sql(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Blank comments, string literals and dollar-quoted bodies; keep identifiers and newlines.

    Returns (masked text, standalone `--` comment lines as (line, text)).
    """
    output: list[str] = []
    dash_comments: list[tuple[int, str]] = []
    index = 0
    length = len(text)
    line = 1
    line_has_code = False
    while index < length:
        char = text[index]
        two = text[index:index + 2]
        if char == "\n":
            output.append(char)
            line += 1
            line_has_code = False
            index += 1
            continue
        if two == "--":
            end = text.find("\n", index)
            end = length if end == -1 else end
            if not line_has_code:
                dash_comments.append((line, text[index:end]))
            output.append(" " * (end - index))
            index = end
            continue
        if two == "/*":
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            output.extend(ch if ch == "\n" else " " for ch in text[index:end])
            line += text.count("\n", index, end)
            index = end
            continue
        if char == "'":
            end = index + 1
            while end < length:
                if text[end] == "'" and text[end + 1:end + 2] == "'":
                    end += 2
                    continue
                if text[end] == "'":
                    break
                end += 1
            output.append("'")
            output.extend(ch if ch == "\n" else " " for ch in text[index + 1:end])
            output.append("'")
            line += text.count("\n", index, end)
            index = end + 1
            line_has_code = True
            continue
        dollar = re.match(r"\$([A-Za-z_]\w*)?\$", text[index:index + 64])
        if dollar:
            tag = dollar.group(0)
            end = text.find(tag, index + len(tag))
            end = length if end == -1 else end + len(tag)
            output.extend(ch if ch == "\n" else " " for ch in text[index:end])
            line += text.count("\n", index, end)
            index = end
            line_has_code = True
            continue
        if not char.isspace():
            line_has_code = True
        output.append(char)
        index += 1
    return "".join(output), dash_comments


def split_statements(masked: str) -> list[SqlStatement]:
    """Split masked SQL on top-level semicolons, keeping each statement's start line."""
    statements: list[SqlStatement] = []
    line = 1
    current_start: int | None = None
    buffer: list[str] = []
    for char in masked:
        if current_start is None and not char.isspace():
            current_start = line
        if char == ";":
            if current_start is not None and "".join(buffer).strip():
                statements.append(SqlStatement(current_start, "".join(buffer)))
            buffer = []
            current_start = None
        else:
            buffer.append(char)
        if char == "\n":
            line += 1
    if current_start is not None and "".join(buffer).strip():
        statements.append(SqlStatement(current_start, "".join(buffer)))
    return statements


def _split_top_level(body: str) -> list[str]:
    """Split a column/action list on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _bare_name(identifier: str) -> str:
    return identifier.split(".")[-1].strip('`"[]')


def detect_engine(statements: list[SqlStatement]) -> str:
    joined = " ".join(statement.text for statement in statements[:200]).upper()
    if re.search(r"\bCONCURRENTLY\b|\bBIGSERIAL\b|\bSERIAL\b|\bJSONB\b|\bTIMESTAMPTZ\b|::", joined):
        return "postgresql"
    if re.search(r"\bAUTO_INCREMENT\b|\bENGINE\s*=|`", joined):
        return "mysql"
    if re.search(r"\bIDENTITY\s*\(|\bNVARCHAR\b|\bGETDATE\s*\(", joined):
        return "sqlserver"
    return "generic"


def check_sql_text(rel_path: str, text: str, engine: str, fk_policy: str, index_prefixes: list[str],
                   unique_prefixes: list[str]) -> list[Finding]:
    """Apply SQL rules to one file: destructive statements, keys, money types, FK policy, index builds, naming."""
    findings: list[Finding] = []
    masked, dash_comments = mask_sql(text)
    statements = split_statements(masked)
    effective_engine = detect_engine(statements) if engine == "auto" else engine
    in_migration = bool(MIGRATION_PATH.search(rel_path))
    created_tables: set[str] = set()
    lock_timeout_set = False
    first_unguarded_key_ddl: tuple[int, str] | None = None

    def add(rule_id: str, severity: str, message: str, line: int, hint: str | None = None) -> None:
        findings.append(Finding(rule_id=rule_id, severity=severity, message=message, path=rel_path, line=line, hint=hint))

    for statement in statements:
        sql = re.sub(r"\s+", " ", statement.text).strip()
        upper = sql.upper()
        line = statement.start_line

        has_where = bool(re.search(r"\bWHERE\b", upper))
        if upper.startswith("DELETE ") and not has_where:
            add("SQL-DELETE-WITHOUT-WHERE", "critical", "DELETE without WHERE removes every row", line,
                "Add a WHERE clause; run destructive data changes only through a reviewed, backed-up runbook (MIG-006).")
        if re.match(r"^UPDATE\s", upper) and not has_where:
            add("SQL-UPDATE-WITHOUT-WHERE", "critical", "UPDATE without WHERE rewrites every row", line,
                "Add a WHERE clause; backfill large tables in chunks with a checkpoint (MIG-003).")
        elif re.match(r"^UPDATE\s", upper) and in_migration:
            add("SQL-BACKFILL-IN-MIGRATION", "low", "data update inside a migration", line,
                "For large tables, backfill in chunks with checkpoint/throttling instead of one long transaction (MIG-003).")
        if upper.startswith("TRUNCATE"):
            add("SQL-TRUNCATE", "high", "TRUNCATE removes all rows and cannot be filtered", line,
                "Confirm scope, backup and restore evidence before any destructive data change (MIG-006).")
        drop = re.match(r"^DROP\s+(TABLE|DATABASE|SCHEMA|VIEW|INDEX|COLUMN|TYPE|FUNCTION)\b", upper)
        if drop:
            severity = "medium" if drop.group(1) in ("INDEX", "VIEW", "FUNCTION") else "high"
            add("SQL-DROP", severity, f"DROP {drop.group(1)} is destructive", line,
                "Use expand/contract: stop reading/writing first, drop after the compatibility window (MIG-004/MIG-007).")
        if LOCK_TIMEOUT_SETTING.match(upper):
            lock_timeout_set = True
        if upper.startswith("LOCK TABLE"):
            add("SQL-EXPLICIT-LOCK", "medium", "explicit table lock", line,
                "Prefer row-level conditional updates; keep lock time short (TX-003).")
        if "ON DELETE CASCADE" in upper:
            add("SQL-CASCADE-DELETE", "medium", "ON DELETE CASCADE can silently remove large data sets", line,
                "Make the delete policy explicit (restrict, soft delete, archive) per DB-005.")

        create_table = re.match(r"^CREATE\s+(?:GLOBAL\s+|LOCAL\s+)?(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`\[\]]+)\s*\((.*)\)",
                                sql, re.IGNORECASE | re.DOTALL)
        if create_table:
            table_name = _bare_name(create_table.group(1))
            created_tables.add(table_name.lower())
            parts = _split_top_level(create_table.group(2))
            has_primary_key = any("PRIMARY KEY" in part.upper() for part in parts)
            if not has_primary_key:
                add("SQL-NO-PRIMARY-KEY", "high", f"table {table_name} has no primary key", line,
                    "Every table needs a primary key / identity strategy (DB-001).")
            if not SNAKE_CASE_NAME.match(table_name):
                add("SQL-TABLE-NAMING", "low", f"table name {table_name} is not lower snake_case", line,
                    "Use lower_snake_case, consistently plural or singular across the schema (references: naming).")
            column_names = []
            for part in parts:
                first_word = part.split()[0] if part.split() else ""
                if first_word.upper() in ("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "INDEX", "KEY", "EXCLUDE"):
                    if "FOREIGN KEY" in part.upper() or " REFERENCES " in f" {part.upper()} ":
                        findings.extend(_foreign_key_finding(rel_path, line, table_name, fk_policy))
                    continue
                column_name = _bare_name(first_word)
                column_names.append(column_name)
                column_type = part[len(first_word):]
                if MONEY_COLUMN.search(column_name) and FLOAT_TYPE.search(column_type):
                    add("SQL-FLOAT-MONEY", "high", f"money column {table_name}.{column_name} uses a binary float type", line,
                        "Use NUMERIC/DECIMAL(p,s) or BIGINT minor units with a currency column (MONEY-002).")
                if re.search(r"\bREFERENCES\b", column_type, re.IGNORECASE):
                    findings.extend(_foreign_key_finding(rel_path, line, table_name, fk_policy))
            if not any(CREATED_AT_COLUMN.match(name) for name in column_names):
                add("SQL-NO-CREATED-AT", "info", f"table {table_name} has no created_at column", line,
                    "Add audit timestamps only if the domain needs them (DB-004).")

        alter_table = re.match(r"^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w.\"`\[\]]+)\s+(.*)$", sql, re.IGNORECASE | re.DOTALL)
        if alter_table:
            table_name = _bare_name(alter_table.group(1))
            is_existing_table = table_name.lower() not in created_tables
            for action in _split_top_level(alter_table.group(2)):
                action_upper = action.upper()
                key_ddl = is_existing_table and _is_key_ddl(action_upper)
                if key_ddl and not lock_timeout_set and first_unguarded_key_ddl is None:
                    first_unguarded_key_ddl = (line, table_name)
                if key_ddl and KEY_CONSTRAINT_ADD.match(action_upper) and "USING INDEX" not in action_upper:
                    if effective_engine == "postgresql":
                        add("SQL-KEY-DDL-BLOCKING", "medium", f"PRIMARY KEY/UNIQUE added to existing table {table_name} builds its index under an exclusive lock",
                            line, "CREATE UNIQUE INDEX CONCURRENTLY first, then ADD CONSTRAINT … USING INDEX (MIG-009, references: keys-under-load).")
                    elif effective_engine == "mysql" and not re.search(r"\bLOCK\s*=\s*NONE\b", upper):
                        add("SQL-KEY-DDL-BLOCKING", "medium", f"key added to existing table {table_name} without LOCK=NONE", line,
                            "Add ALGORITHM=INPLACE, LOCK=NONE so MySQL refuses instead of blocking writes (MIG-009).")
                if (key_ddl and effective_engine == "postgresql" and re.search(r"\bREFERENCES\b|\bFOREIGN\s+KEY\b", action_upper)
                        and "NOT VALID" not in action_upper):
                    add("SQL-FK-VALIDATES-UNDER-LOCK", "medium", f"foreign key on existing table {table_name} validates every row while locking both tables",
                        line, "ADD CONSTRAINT … NOT VALID, then VALIDATE CONSTRAINT in a separate transaction (MIG-009).")
                add_column = re.match(r"^ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([\w\"`\[\]]+)\s+(.*)$", action, re.IGNORECASE | re.DOTALL)
                if add_column and add_column.group(1).upper() not in ("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "INDEX", "KEY", "CHECK"):
                    column_name = _bare_name(add_column.group(1))
                    definition = add_column.group(2).upper()
                    if "NOT NULL" in definition and "DEFAULT" not in definition and table_name.lower() not in created_tables:
                        add("SQL-ADD-NOT-NULL-NO-DEFAULT", "high", f"{table_name}.{column_name} added NOT NULL without DEFAULT", line,
                            "Add nullable → backfill in chunks → set NOT NULL, so old app versions keep working (MIG-002/MIG-004).")
                    if MONEY_COLUMN.search(column_name) and FLOAT_TYPE.search(definition):
                        add("SQL-FLOAT-MONEY", "high", f"money column {table_name}.{column_name} uses a binary float type", line,
                            "Use NUMERIC/DECIMAL(p,s) or BIGINT minor units (MONEY-002).")
                if re.search(r"\bREFERENCES\b|\bFOREIGN\s+KEY\b", action_upper):
                    findings.extend(_foreign_key_finding(rel_path, line, table_name, fk_policy))
                if re.match(r"^DROP\s+(COLUMN\s+)?", action_upper) and not re.match(r"^DROP\s+(CONSTRAINT|INDEX|KEY|PRIMARY\s+KEY|FOREIGN\s+KEY|DEFAULT|NOT\s+NULL)\b", action_upper):
                    add("SQL-DROP-COLUMN", "high", f"column dropped from {table_name}", line,
                        "Drop only after no running app version reads or writes it (expand/contract, MIG-004).")
                if action_upper.startswith("RENAME"):
                    add("SQL-RENAME", "high", f"rename on {table_name} breaks running app versions", line,
                        "Add the new name, dual-write/backfill, switch reads, then drop the old one (MIG-002).")
                type_change = TYPE_CHANGE.match(action)
                if type_change:
                    column_name = _bare_name(type_change.group(1) or type_change.group(2) or type_change.group(3))
                    if KEY_COLUMN.match(column_name):
                        add("SQL-KEY-TYPE-CHANGE", "high", f"key column {table_name}.{column_name} changes type", line,
                            "Rewrites the table and its indexes under an exclusive lock; every logical reference must change too. "
                            "Use a new column + dual write + chunked backfill + short swap (MIG-009, references: keys-under-load).")
                    else:
                        add("SQL-ALTER-TYPE", "medium", f"column type change on {table_name}", line,
                            "May rewrite the table under an exclusive lock; measure on production-like volume first (MIG-001).")

        create_index = re.match(r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`\[\]]+)?\s*ON\s+(?:ONLY\s+)?([\w.\"`\[\]]+)",
                                sql, re.IGNORECASE)
        if create_index:
            is_unique = bool(create_index.group(1))
            is_concurrent = bool(create_index.group(2))
            index_name = _bare_name(create_index.group(3) or "")
            table_name = _bare_name(create_index.group(4))
            prefixes = unique_prefixes if is_unique else index_prefixes
            if index_name and not index_name.lower().startswith(tuple(prefixes)):
                add("SQL-INDEX-NAMING", "low", f"index {index_name} does not use prefix {' / '.join(prefixes)}", line,
                    f"Name indexes {prefixes[0]}<table>_<columns> so purpose is visible.")
            if effective_engine == "postgresql" and not is_concurrent and table_name.lower() not in created_tables:
                add("SQL-INDEX-BLOCKS-WRITES", "medium", f"CREATE INDEX on existing table {table_name} blocks writes while it builds",
                    line, "On large tables use CREATE INDEX CONCURRENTLY outside a transaction block (MIG-001, plan §16.1).")
            if is_concurrent:
                add("SQL-INDEX-CONCURRENTLY", "info", f"concurrent index build on {table_name}", line,
                    "Cannot run inside a transaction block; on failure it leaves an INVALID index to drop and retry.")

        if re.search(r"\bSELECT\s+\*", upper) and (upper.startswith(("CREATE", "INSERT"))):
            add("SQL-SELECT-STAR", "low", "SELECT * in a view/migration couples it to every column", line,
                "List columns explicitly (IDX-006).")

    if first_unguarded_key_ddl is not None:
        key_line, key_table = first_unguarded_key_ddl
        add("SQL-KEY-DDL-NO-LOCK-TIMEOUT", "medium", f"key/constraint DDL on existing table {key_table} without a lock timeout", key_line,
            "SET lock_timeout (MySQL: lock_wait_timeout) before it and retry a bounded number of times: DDL waiting behind a "
            "long transaction blocks every later query on the table (MIG-009).")
    findings.extend(_dash_comment_style(rel_path, dash_comments))
    return findings


def _is_key_ddl(action_upper: str) -> bool:
    """True for ALTER TABLE actions that take strong locks on keys: add/validate/drop constraints, key type changes."""
    if KEY_CONSTRAINT_ADD.match(action_upper) or re.search(r"\bREFERENCES\b|\bFOREIGN\s+KEY\b", action_upper):
        return True
    if re.match(r"^(VALIDATE\s+CONSTRAINT|DROP\s+(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|INDEX|KEY)\b)", action_upper):
        return True
    type_change = TYPE_CHANGE.match(action_upper)
    return bool(type_change and KEY_COLUMN.match(_bare_name(type_change.group(1) or type_change.group(2) or type_change.group(3))))


def _foreign_key_finding(rel_path: str, line: int, table_name: str, fk_policy: str) -> list[Finding]:
    if fk_policy == "allowed":
        return []
    severity = "high" if fk_policy == "forbidden" else "medium"
    return [Finding(
        rule_id="SQL-FOREIGN-KEY",
        severity=severity,
        message=f"foreign key on {table_name} (project policy: {fk_policy})",
        path=rel_path,
        line=line,
        hint="Without an FK, document the integrity owner, race handling, delete policy, index and orphan reconciliation (plan §14.2).",
    )]


def _dash_comment_style(rel_path: str, dash_comments: list[tuple[int, str]]) -> list[Finding]:
    """User preference: multi-line comments use /* ... */, also in SQL."""
    findings: list[Finding] = []
    run_start: int | None = None
    previous_line = -10
    count = 0
    for line, _text in dash_comments + [(10**9, "")]:
        if line == previous_line + 1:
            count += 1
        else:
            if count >= 3 and run_start is not None:
                findings.append(Finding("SQL-MULTILINE-COMMENT", "low", f"{count} consecutive -- lines form a multi-line comment",
                                        rel_path, run_start, "Project style: multi-line comments use /* ... */ (DOC-005)."))
            run_start = line
            count = 1
        previous_line = line
    return findings


def check_orm_foreign_keys(rel_path: str, text: str, fk_policy: str) -> list[Finding]:
    """Find ORM relations that create DB foreign keys, with the ORM-specific way to avoid them."""
    if fk_policy == "allowed":
        return []
    suffix = PurePosixPath(rel_path).suffix.lower()
    findings: list[Finding] = []
    reported_lines: set[int] = set()
    severity = "high" if fk_policy == "forbidden" else "medium"
    for pattern in ORM_FOREIGN_KEY_PATTERNS:
        if suffix not in pattern.suffixes:
            continue
        if pattern.disabled_marker is not None and pattern.orm == "Prisma" and pattern.disabled_marker.search(text):
            continue
        for match in pattern.regex.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            statement_end = text.find(")", match.end())
            window = text[line_start:(statement_end if statement_end != -1 else match.end()) + 200]
            if pattern.disabled_marker is not None and pattern.disabled_marker.search(window):
                continue
            line = text.count("\n", 0, match.start()) + 1
            if line in reported_lines:
                continue
            reported_lines.add(line)
            findings.append(Finding(
                rule_id="ORM-FOREIGN-KEY",
                severity=severity,
                message=f"{pattern.orm} relation creates a database foreign key (policy: {fk_policy})",
                path=rel_path,
                line=line,
                hint=pattern.hint,
            ))
    return findings


def run(args: argparse.Namespace) -> int:
    """CLI handler for `check-sql`: SQL files plus ORM model/migration code among the selected files."""
    repo_root = resolve_repo_root(args.repo)
    profile, profile_warnings = load_profile(repo_root)
    database_profile = profile["database"]
    engine = args.engine or database_profile["engine"]
    fk_policy = args.fk_policy or database_profile["foreign_key_policy"]
    fail_on = args.fail_on or profile["code"]["fail_on"]
    started_at = utc_now_iso()
    scope = "all" if args.all else "changed"
    targets = select_target_files(repo_root, args.paths, scope, args.base)

    findings: list[Finding] = []
    sql_files = 0
    orm_files = 0
    for rel_path in targets:
        suffix = PurePosixPath(rel_path).suffix.lower()
        if suffix not in ORM_SUFFIXES and suffix != ".sql":
            continue
        text = read_text_limited(repo_root / rel_path, 4 * 1024 * 1024)
        if text is None:
            continue
        if suffix == ".sql":
            sql_files += 1
            findings.extend(check_sql_text(rel_path, text, engine, fk_policy,
                                           database_profile["index_prefixes"], database_profile["unique_index_prefixes"]))
        elif suffix == ".prisma" or ORM_MODEL_PATH.search(rel_path):
            orm_files += 1
            findings.extend(check_orm_foreign_keys(rel_path, text, fk_policy))

    gate = gate_from_findings(findings, fail_on)
    result = CheckResult(
        check_id=getattr(args, "check_id", "db.sql_static"),
        tool="devskills.check-sql",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="findings" if findings else "clean",
        summary=f"{sql_files} SQL + {orm_files} ORM files ({scope}); {severity_summary(findings)}",
        findings=findings,
        details={
            "engine": engine,
            "foreign_key_policy": fk_policy,
            "fail_on": fail_on,
            "profile_warnings": profile_warnings,
            "limitations": "Static text analysis: validate lock impact and query plans on an isolated DB of the same engine/version (IDX-004, MIG-005).",
        },
        started_at=started_at,
    )
    lines = [f"check-sql: {result.summary} [engine={engine}, fk_policy={fk_policy}]"]
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)
