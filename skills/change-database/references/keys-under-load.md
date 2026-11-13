# Keys and references while large transactions run (TX-010, MIG-009)

Use this when a new task adds or changes a primary key, unique key, reference column (`<entity>_id`), FK (where allowed) or the code that checks/locks parent and child rows — on tables that batches, imports, reports, reconciliations or other long units of work also touch.

"Fast" key DDL is not safe by default. The DDL first waits for an exclusive lock; while it waits, **every new query on that table queues behind it**. One 20-minute batch transaction plus one `ALTER TABLE … ADD CONSTRAINT` is enough to stop all reads and writes on the table.

## 1. Find the large transactions first

List every long unit of work that touches the affected tables (CTX-003): nightly batches, imports, exports and reports running in a transaction, reconciliation jobs, admin bulk actions, `transaction.atomic()` around loops. Record their schedule, lock order (which table first), and typical duration.

Read-only checks (allowed on any target; see SKILL.md → Local data and authorization):

```sql
-- PostgreSQL: oldest open transactions and who blocks whom
SELECT pid, now() - xact_start AS xact_age, state, left(query, 80) AS query
FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 10;
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, left(query, 80) AS query
FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;

-- MySQL/InnoDB: long transactions, metadata locks, row lock waits
SELECT trx_id, trx_started, trx_rows_locked, left(trx_query, 80) FROM information_schema.innodb_trx ORDER BY trx_started;
SELECT object_name, lock_type, lock_status, owner_thread_id FROM performance_schema.metadata_locks WHERE object_schema = DATABASE();
SELECT * FROM sys.innodb_lock_waits;
```

## 2. Schema changes on keys: online form + lock timeout

Every key/constraint DDL on an existing table sets a lock timeout and is retried a bounded number of times, never left to wait indefinitely:

```sql
SET lock_timeout = '3s';         -- PostgreSQL (SET LOCAL inside a transaction)
SET statement_timeout = '15min'; -- upper bound for the build/validate step
-- MySQL: SET SESSION lock_wait_timeout = 3;  (metadata lock wait, seconds)
```

| Change | Blocking form (avoid on large/busy tables) | Online form |
| --- | --- | --- |
| Add PK / UNIQUE to existing table (PostgreSQL) | `ALTER TABLE t ADD PRIMARY KEY (id)` builds the index under ACCESS EXCLUSIVE | `CREATE UNIQUE INDEX CONCURRENTLY uq_t_id ON t (id);` then `ALTER TABLE t ADD CONSTRAINT t_pkey PRIMARY KEY USING INDEX uq_t_id;` (column must already be NOT NULL: add `CHECK (id IS NOT NULL) NOT VALID`, `VALIDATE`, then `SET NOT NULL` uses the check on PG 12+) |
| Add FK (only when the user chose one, see fk-free-integrity.md) | `ADD FOREIGN KEY …` validates every row while locking both tables | `ADD CONSTRAINT … FOREIGN KEY … NOT VALID;` then, in a separate transaction, `VALIDATE CONSTRAINT …` (weaker lock: reads and writes continue) |
| PK/reference type `INT → BIGINT` | `ALTER COLUMN id TYPE bigint` rewrites the table and every index under an exclusive lock | expand/contract: new `id_new BIGINT` column, dual-write (trigger or app), chunked backfill, `CREATE UNIQUE INDEX CONCURRENTLY`, one short swap transaction; migrate every logical reference column (`*_id` in other tables, caches, events) in the same plan |
| Change PK values | `UPDATE t SET id = …` takes the strongest row lock and breaks references | do not; add a new business key instead |
| MySQL add PK/UNIQUE/column | default may copy the table | `ALTER TABLE … , ALGORITHM=INPLACE, LOCK=NONE` so MySQL refuses instead of silently blocking; very large tables: online schema-change tool (gh-ost/pt-osc) by an approved runbook |
| Drop constraint/index | short exclusive lock, still queues behind long transactions | same lock timeout + retry; `DROP INDEX CONCURRENTLY` on PostgreSQL |

Rules:

- One key DDL per migration transaction; never in the same transaction as a backfill (MIG-003).
- Run outside the windows of the large transactions found in step 1, or pause them; record the window and stop condition in the migration note (MIG-001).
- Framework switches: Django `atomic = False` for concurrent operations, `django.contrib.postgres.operations.AddIndexConcurrently` / `AddConstraintNotValid` + `ValidateConstraint`; Alembic `with op.get_context().autocommit_block():`; Laravel `DB::statement('SET lock_timeout …')` in the migration; Rails `disable_ddl_transaction!`.

## 3. New code that locks parents or children next to a large transaction

FK-free integrity (fk-free-integrity.md) adds parent locks or conditional inserts. They now compete with every existing long transaction on the same rows.

| Risk | Rule |
| --- | --- |
| Deadlock: batch locks `orders` then `order_items`, new code locks `order_items` then `orders` | Follow the lock order the existing large transactions already use (parent → child is the usual one); write the order in the use-case docstring (TX-005) |
| New code blocked for the whole batch duration | The batch updates in chunks with a commit per chunk (MIG-003, plan §11), so no lock is held longer than one chunk |
| Parent check stronger than needed | PostgreSQL: `SELECT … FOR KEY SHARE` for "parent must exist and keep its key" — compatible with ordinary `UPDATE`s of non-key columns; use `FOR UPDATE` only when the parent's data changes. MySQL: `FOR SHARE`, and expect gap locks under REPEATABLE READ |
| Updates of key columns | An `UPDATE` touching a PK/unique column takes the strongest row lock (PostgreSQL `FOR UPDATE`) and blocks every child check on that parent; keep keys immutable |
| Delete parent checks children without an index | The existence check scans the child table while holding the parent lock: index every reference column, composite with `tenant_id` (DB-001, fk-free-integrity.md §4) |
| SQL Server lock escalation | Thousands of row locks in one statement escalate to a table lock (≈5,000); keep chunks below that |

## 4. Performance side effects of large transactions on keys

- **Rollback cost:** undoing a large transaction takes about as long as doing it; plan chunk size by acceptable rollback time.
- **MVCC bloat:** a long open transaction keeps old row versions (PostgreSQL vacuum horizon, InnoDB undo history). New indexes and backfills then read more pages; watch `n_dead_tup` / history list length.
- **Replication lag:** one huge commit replays as one unit on replicas.
- **PK choice under write load:** sequential keys (identity, UUIDv7) append to the index; random UUIDv4 splits pages and, in InnoDB, reorders the clustered table (DB-007). Very high insert rates on one sequential key can contend on the last index page — measure before switching.
- **Each new unique/reference index costs every insert/update**, including the large batch; measure batch duration before and after (IDX-001).

## 5. Verify

On an isolated database with the production engine/version and realistic volume (test-safely, verification-db.md):

1. **DDL behind a long transaction:** session A `BEGIN; UPDATE t SET … WHERE id < 10000;` (no commit). Session B runs the migration with its lock timeout: it must **fail fast** with a lock timeout, not hang. Session C's ordinary `SELECT` must not stay blocked longer than the timeout. Commit A; B's retry succeeds.
2. **Deadlock between the new path and the batch:** run the batch chunk and the new use case concurrently with a barrier (like the two-buyer test); expect no deadlock, or a bounded retry of the whole unit (TX-006).
3. **Invariant after the change:** row counts, duplicate check on the new key, orphan query on the reference column — before and after.
4. **Timing:** batch duration and p95 of the affected endpoint before/after the new index or lock.

Record in the migration note: tables, large transactions found, lock mode, lock timeout and retries, window, stop condition, verification query.
