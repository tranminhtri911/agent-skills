# Long transactions that time out the whole system (TX-003, TX-005, TX-011)

One slow transaction rarely fails alone. It holds locks and a pooled connection; everything that needs those rows or that pool waits behind it, and the waiting spreads until unrelated endpoints time out.

## How the cascade happens

1. Transaction T holds row locks — often a **hot row** (tenant counter, balance, settings, inventory of a best-seller) — and one pooled connection for seconds or minutes.
2. Requests touching the same rows wait on the lock. Each waiter holds **its own** connection and worker thread while it waits.
3. The pool empties. Requests that never touch those rows now wait to acquire a connection → timeouts across the API.
4. Clients and load balancers time out and retry → more waiters (retry storm). The app gave up, but the database statement keeps waiting or running, so locks and connections stay held.
5. Side effects: MVCC bloat / InnoDB undo growth slows every query, replicas lag, and any DDL queues behind T and blocks the table (keys-under-load.md).

## Causes to look for in the diff

| Cause | Fix |
| --- | --- |
| HTTP/payment/email/upload/sleep inside the transaction | After commit: `transaction.on_commit`, `DB::afterCommit`/`afterCommit` jobs, outbox (design-reliability). `check-code` flags `PY-SLOW-CALL-IN-TRANSACTION` / `PHP-SLOW-CALL-IN-TRANSACTION` |
| Request-wide transaction: Django `ATOMIC_REQUESTS`, Spring `@Transactional` on controllers + open-session-in-view, middleware that wraps the request, streaming responses/generators consumed inside it | Transaction around the use case only; `spring.jpa.open-in-view=false`; build the response after commit |
| Whole batch/import/report in one transaction | Chunks with a checkpoint committed per chunk (MIG-003, plan §11) |
| Hot row locked first, slow work after | Lock hot rows **last**, as the final short statement; or conditional `UPDATE`, append-only rows aggregated later, sharded counters |
| `SELECT … FOR UPDATE` on a range or an unindexed predicate | Lock by primary key; index the predicate (gap/next-key locks in InnoDB) |
| `BEGIN` in a console, admin script or paused debugger; exception path that neither commits nor rolls back | Context managers; server-side idle-in-transaction timeout; pool resets connections on return |
| Waiting for another lock with no limit | `lock_timeout` / `innodb_lock_wait_timeout` per role or session |

## Guardrails

**Timeout ladder — each inner layer fires before the outer one**, so the database gives up (and releases locks) before anyone above it stops listening:

`lock_timeout` < `statement_timeout` / transaction timeout ≤ pool acquire timeout < app request timeout < proxy/LB timeout < client timeout.

Example for an interactive API with a 10 s budget: lock 2 s, statement 5 s, acquire 3 s, request 8 s, LB 10 s. Batches get their own, longer limits — but still bounded and still chunked.

Set them in code with the connection, not by hand on a shared server (changing roles or server settings on dev/staging/production is a config change that needs authorization):

| Stack | Where |
| --- | --- |
| PostgreSQL (any client) | connection option `-c lock_timeout=2000 -c statement_timeout=5000 -c idle_in_transaction_session_timeout=30000`; PostgreSQL 17+: `transaction_timeout`; or `ALTER ROLE app_web SET …` via a reviewed migration |
| Django | `DATABASES[...]["OPTIONS"] = {"options": "-c lock_timeout=2000 -c statement_timeout=5000"}` |
| SQLAlchemy | `create_engine(url, connect_args={"options": "-c statement_timeout=5000"}, pool_timeout=3)` |
| node-postgres | `new Pool({ statement_timeout: 5000, idle_in_transaction_session_timeout: 30000, connectionTimeoutMillis: 3000 })` |
| Prisma | `$transaction(fn, { maxWait: 2000, timeout: 5000 })` |
| Spring | `@Transactional(timeout = 5)`, Hikari `connection-timeout`, `spring.jpa.open-in-view=false` |
| Laravel (pgsql) | `DB::statement("SET lock_timeout = '2s'")` per connection in a service provider; MySQL: `SET SESSION innodb_lock_wait_timeout = 3` |
| MySQL | `innodb_lock_wait_timeout` (default 50 s — far too long for web requests), `max_execution_time` (SELECT only), no idle-in-transaction timeout → enforce in the app |
| SQL Server | `SET LOCK_TIMEOUT 2000`; client command timeout |

**Contain the blast radius:**

- Separate pools (and DB roles) for web and batch/report workers; the batch pool is small so it cannot take the web pool's connections (`ds.py pool-budget` with one `--group` each).
- Long reads/reports go to a replica or snapshot export, not a transaction on the primary.
- A lock or statement timeout maps to a documented busy response (409/503 + `Retry-After`), not a 500 (design-api); retries are bounded with jitter and stop at the caller's deadline (design-reliability).
- Shed load when pool wait p95 crosses a threshold instead of queueing without limit.

## Detect

Alert on: oldest transaction age, idle-in-transaction sessions, lock wait count/duration, pool wait p95 and pool in-use = max, deadlocks. PostgreSQL: `log_lock_waits = on`, `log_min_duration_statement`. MySQL: slow query log, `SHOW ENGINE INNODB STATUS`.

```sql
-- PostgreSQL: transactions older than 30 s and who blocks whom (read-only)
SELECT pid, now() - xact_start AS xact_age, state, wait_event_type, pg_blocking_pids(pid) AS blocked_by, left(query, 80) AS query
FROM pg_stat_activity WHERE xact_start < now() - interval '30 seconds' ORDER BY xact_start;
-- MySQL
SELECT trx_mysql_thread_id, trx_started, trx_rows_locked, left(trx_query, 80)
FROM information_schema.innodb_trx WHERE trx_started < NOW() - INTERVAL 30 SECOND ORDER BY trx_started;
```

## While it is happening

1. Find the **root blocker** (the session at the top of `blocked_by`), not the waiters.
2. Cancel before terminate: `pg_cancel_backend(pid)` stops the statement; `pg_terminate_backend(pid)` ends the session and rolls the transaction back — the rollback can take as long as the work did. MySQL: `KILL QUERY id`, then `KILL id`.
3. Cancelling or killing sessions on dev, staging, production or a shared database is a dangerous operation: ask first unless that exact action is already authorized (dev-orchestrate). On a local disposable database, proceed.
4. Afterwards: fix the cause, add the missing guardrail, add the test below.

## Verify

On an isolated database with the production engine (test-safely):

| Check | Pass criterion |
| --- | --- |
| Lock wait fails fast | Session A `BEGIN; SELECT … FOR UPDATE` on a row; the endpoint touching that row returns the busy response within `lock_timeout` + margin, not the request timeout; endpoints on other rows keep their p95 |
| Pool exhaustion is contained | Hold pool-size connections in open transactions; the next request fails with an acquire timeout quickly; a health check without DB still answers |
| Idle transaction is ended | Open a transaction and leave it idle; the server ends it after the configured timeout |
| Settings are live | An integration test runs `SHOW statement_timeout` / `SELECT @@innodb_lock_wait_timeout` through the app's own connection |
| No slow calls inside transactions | `ds.py check-code` reports no `*-SLOW-CALL-IN-TRANSACTION` |

```python
def test_cancel_fails_fast_while_order_row_is_locked(self):  # TransactionTestCase: real commits
    order = make_order()
    with psycopg.connect(TEST_DSN, autocommit=False) as blocker:  # second connection to the same test DB
        blocker.execute("SELECT id FROM orders WHERE id = %s FOR UPDATE", [order.id])
        started = time.monotonic()
        response = self.client.post(f"/api/orders/{order.id}/cancel")
        self.assertEqual(response.status_code, 409)  # the documented busy response
        self.assertLess(time.monotonic() - started, 3.0)  # lock_timeout 2 s + margin
        blocker.rollback()
```
