---
name: change-database
description: "Use when analyzing, specifying, reviewing or changing anything that reads or writes a database — tables, keys, columns, indexes, migrations, queries, ORM models or repositories, deleting data, transactions, locks, long transactions, multi-step CRUD that must roll back together, or connection pools. Triggers (vi): xóa dữ liệu, thêm/sửa bảng hoặc cột, index, truy vấn, migration, giao dịch, khóa bản ghi, sao lưu/khôi phục, danh sách, báo cáo, CRUD. Applies even when the request is phrased as a question (\"làm sao…\", \"có thể … không?\"); load it together with dev-orchestrate, not after it."
metadata:
  version: "1.0.0"
  suite: devskills
---

# Change Database

Correct data first, then contention and speed. Atomic units of work with automatic rollback, short transactions, indexes justified by real queries, schemas that scale and evolve safely — and the project default of **no new database foreign keys**, with integrity designed explicitly instead.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

**Start from the project's base (CTX-009).** New tables and models follow the existing base model (timestamps, soft delete, tenant column, id strategy), naming, migration tool and migration style of the repo; read two recent migrations before writing one. Status/type columns use the project's enum or choices class (`choices=OrderStatus.choices`, enum casts), and queries filter by the enum, not a literal (CODE-011); migrations and seeds may keep literal values. Status changes go through the one transition function with a lock or conditional update (implement-backend BE-011). Query helpers go where the source puts them (QuerySet/Manager, scope, repository if the project has one) — no repository layer added over the ORM (DES-007).

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Schema change, data deletion or more than one reasonable approach → **REQUIRED:** design-change.
- The same unit of work also calls a payment, email, queue, file store or external API, or a job must not run twice or die halfway → **REQUIRED:** design-reliability.
- Bulk deletes/updates, batches over many rows, N+1 or pool exhaustion → **REQUIRED:** review-performance.
- Tenant filters, who may delete or read which rows, dynamic SQL → **REQUIRED:** review-security.
- Any test, seed or SQL test script that writes data → **REQUIRED:** test-safely.

## Local data and authorization

Process in-scope local data and development databases directly, including necessary resets, bulk changes and migration rollbacks; do not ask merely because SQL changes data. Check the actual database target and preserve unrelated data. Ask for dangerous DB commands only when the target is known or reasonably suspected to be non-local (dev, STG/staging, production or shared servers), unless the same target and effect are already authorized. Read-only remote queries do not trigger this confirmation rule. A localhost tunnel can still target a remote DB (dev-orchestrate → authorization rules). Tests use a disposable database created for the run.

## Table design (DB-001…DB-008)

- Every table: primary key strategy, owner module, lifecycle, meaning of business columns. Names: lower snake_case, one convention for plural/singular, `<entity>_id` for references, `is_/has_` booleans, units in names (`amount_minor`, `duration_ms`).
- Types/precision/nullability/defaults/CHECK/UNIQUE follow the domain; no string/JSON dumping for data you must query or validate.
- Money: `NUMERIC(p,s)` or `BIGINT` minor units + `currency`; never FLOAT/DOUBLE (MONEY-002).
- Timestamps with time zone (`created_at`, `updated_at`) when the domain needs audit/sync; `version` column for optimistic locking when used.
- Soft delete needs uniqueness, filtering, restore and retention rules. Template and naming conventions: [table-design.md](references/table-design.md).

## Foreign keys: discouraged by project policy

Do not add new DB foreign keys; do not drop existing ones without a migration plan. For every relation without an FK document: the single writer/owner, how parent existence is checked and races with parent deletion are prevented, delete policy, the index on the reference column, and an orphan reconciliation job. Checklist and ORM switches (`db_constraint=False`, `relationMode = "prisma"`, no `constrained()`, …): [fk-free-integrity.md](references/fk-free-integrity.md). For money/ledger/permissions present the FK-vs-no-FK tradeoff to the user.

## Indexes and query plans (IDX-001…IDX-009)

Each new index names the query it serves, its selectivity, column order (equality → range → sort), and its write/storage cost. Check existing indexes for duplicates. Validate with `EXPLAIN` on realistic synthetic volume in an isolated DB — `EXPLAIN ANALYZE` executes the query. Never drop an index that enforces uniqueness because usage looks low.

**Plan evidence for large data (IDX-008).** Every new or changed query that can read or write a large or growing table — about 100k+ rows, unknown size, or unbounded (lists, search, reports, exports, bulk UPDATE/DELETE, delete procedures, batches) — gets its plan read before handover, not only new indexes. Record engine and version, synthetic row counts, access path and index used, estimated vs actual rows and duration; before/after when an existing query changes. Look for scans of large tables, estimates off by 10×+, sorts or hashes spilling to disk, per-row lookups, implicit type conversions (SQL Server `CONVERT_IMPLICIT`, e.g. `nvarchar` parameter vs `varchar` column) and functions on indexed columns.

**Which plan where — its effect on the database (IDX-009).** An *estimated* plan (`EXPLAIN`; SQL Server `SET SHOWPLAN_XML ON`; Oracle `EXPLAIN PLAN`) only compiles the statement: cheap, no data change, allowed wherever read access is (Oracle writes to `PLAN_TABLE`). An *actual* plan (`EXPLAIN ANALYZE`, MySQL `EXPLAIN ANALYZE`, SQL Server `SET STATISTICS XML ON`) **runs the whole statement** — full CPU/IO, locks, and for INSERT/UPDATE/DELETE the rows really change (PostgreSQL `BEGIN … ROLLBACK` undoes them but holds the locks until rollback). Actual plans run only on an isolated or local database with synthetic volume; on dev/STG/production use estimated plans, and an actual plan there needs explicit approval and is never run for DML. Per-engine commands: [query-and-orm.md → Query plans](references/query-and-orm.md#query-plans-safely-per-engine-idx-008-idx-009).

## Transactions and concurrency (TX-001…TX-011)

- The use case owns the unit of work; all writes that must be atomic share one transaction; any exception rolls back (framework helpers: `session.begin()`, `transaction.atomic`, `DB::transaction`, `@Transactional`, `prisma.$transaction`).
- Keep transactions short: no user waits, remote calls, sleeps or heavy CPU inside (`check-code`: `*-SLOW-CALL-IN-TRANSACTION`). Lock hot rows (counters, balances, settings) last, not first.
- One long transaction can time out the whole system: its waiters each hold a pooled connection until the pool is empty (TX-011). Every connection gets a timeout ladder — `lock_timeout` < `statement_timeout` ≤ pool acquire < request < proxy timeout — plus an idle-in-transaction limit; batch/report work uses its own small pool and chunked commits; a lock timeout maps to a busy response, not a 500. Causes, per-stack settings, detection, runbook and fail-fast tests: [long-transactions.md](references/long-transactions.md).
- Prevent lost updates/oversell with conditional updates (`… WHERE available >= :qty` and check affected rows), version checks, or row locks in a consistent order. "No lock at all" is not a goal; minimal lock time is.
- Retry deadlocks/serialization failures only for whole, safe units, a bounded number of times; never retry when the commit outcome is unknown — look it up by operation id.
- Several systems (DB + payment + email): transaction + outbox + idempotent consumer + compensation (design-reliability). Details: [transactions-and-migrations.md](references/transactions-and-migrations.md).

## Keys and references next to large transactions (TX-010, MIG-009)

A task that adds or changes a PK, unique key, reference column or FK — or adds parent/child locking for FK-free integrity — on tables that batches, imports, reports or other long transactions also touch:

- First list those large transactions: schedule, duration, lock order (read-only `pg_stat_activity` / `information_schema.innodb_trx`).
- Key DDL on an existing table sets `lock_timeout` (MySQL `lock_wait_timeout`) with bounded retry; otherwise it queues behind the long transaction and every new query on the table queues behind it. Use the online form: `CREATE UNIQUE INDEX CONCURRENTLY` + `ADD CONSTRAINT … USING INDEX`, FK `NOT VALID` + `VALIDATE`, `INT → BIGINT` keys by expand/contract — never `ALTER COLUMN id TYPE` on a large table.
- New locking code follows the lock order the large transactions already use, takes the weakest sufficient lock (`FOR KEY SHARE` for parent existence), never updates key values; the large transaction commits per chunk.
- Verify on an isolated engine: the migration fails fast while another session holds a long transaction; new path + batch run concurrently without deadlock; batch duration and endpoint p95 before/after.

Online forms per engine, lock modes, performance side effects (rollback cost, MVCC bloat, PK choice) and the tests: [keys-under-load.md](references/keys-under-load.md).

## Migrations (MIG-001…MIG-009)

Expand → backfill in checkpointed chunks → switch reads/writes → contract after the compatibility window. State lock impact, duration, stop condition and recovery for each migration; test on the same engine/version with synthetic data. PostgreSQL: `CREATE INDEX CONCURRENTLY` outside a transaction for large tables. "Rollback" is written only when you know what happens to new data; otherwise roll forward.

## Connection pools (POOL-001…POOL-006)

One engine/pool per process, one session per request/job/task, explicit pool size/overflow/acquire timeout, cleanup on success, error and cancellation, no live connections inherited across fork. Budget at deployment **peak**: `DS pool-budget --group web:3:2:5:1 --surge-percent 100 --other 20 --db-max 80`. Settings per stack: [connection-pools.md](references/connection-pools.md). Provisioning the database itself (RDS/Aurora/Cloud SQL: private subnets, encryption, TLS, backups, IAM auth): design-infrastructure.

## Find every writer first

Before renaming or retyping a column, changing a model or adding a constraint, list every code path that reads or writes it (CTX-003): search the table/model name, and when the optional CodeGraph integration is available use `codegraph callers <ModelOrRepository> --json` and `codegraph impact <Symbol> --json` to include jobs, admin tools and imports.

## Verify

`DS native-checks --execute --run <id>` includes framework migration checks (Django `makemigrations --check --dry-run`). `DS check-sql` (changed SQL + ORM files: destructive statements, missing PK, float money, FK policy, blocking index builds, blocking key/constraint DDL, key type changes, missing lock timeout, naming) → integration tests on an isolated real engine via test-safely (rollback at each step, two concurrent buyers for the last item, duplicate key). SQLite does not prove PostgreSQL/MySQL locking or migration behaviour.

Engine fixtures, concurrent transactions, rollback at every step, migration compatibility with the running app, backfill resume and query counts: [verification-db.md](references/verification-db.md). N+1, lost updates, transaction scope, EXPLAIN-driven indexes and keyset pagination: [query-and-orm.md](references/query-and-orm.md).
