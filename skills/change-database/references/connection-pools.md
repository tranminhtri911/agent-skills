# Connection pool settings by stack

Budget = Σ over every process at deployment peak of (pool size + overflow) + workers/batch/migrations/admin + reserve ≤ the database's usable max connections. Check with `ds.py pool-budget`. Use a pooler (PgBouncer, RDS Proxy) when processes × pool exceed the budget.

| Stack | Where | Key settings |
| --- | --- | --- |
| SQLAlchemy 2.x | `create_engine(url, pool_size=5, max_overflow=1, pool_timeout=10, pool_pre_ping=True, pool_recycle=1800)` once per process (lifespan/app factory) | `Session`/`AsyncSession` per request/task; `engine.dispose()` after fork in workers |
| Django | `CONN_MAX_AGE` (persistent connections), `CONN_HEALTH_CHECKS = True`; pooling via `OPTIONS["pool"]` (psycopg 3, Django 5.1+) or PgBouncer | one connection per thread; close in long-running scripts |
| node-postgres | `new Pool({ max: 10, idleTimeoutMillis: 30000, connectionTimeoutMillis: 5000 })` module singleton | always `client.release()` in `finally`; `pool.end()` on shutdown |
| Prisma | `connection_limit` and `pool_timeout` in the URL; one `PrismaClient` per process | serverless: use a pooler/accelerate |
| Laravel | PHP-FPM: one connection per worker process (no pool); size = FPM `pm.max_children` × servers | queue workers: `--max-jobs`/`--max-time` to recycle |
| Spring (HikariCP) | `spring.datasource.hikari.maximum-pool-size`, `connection-timeout`, `max-lifetime` | `@Transactional` scope = connection hold time |
| .NET (Npgsql/SqlClient) | `Maximum Pool Size`, `Timeout` in the connection string; DbContext scoped | `await using` contexts; no singleton DbContext |
| Go database/sql | `db.SetMaxOpenConns`, `SetMaxIdleConns`, `SetConnMaxLifetime` | `defer rows.Close()`; contexts with deadlines |

Signals of trouble: pool wait time rising, `too many connections`, idle-in-transaction sessions, connections leaked by code paths that skip `close()` on errors. A single long transaction can drain the pool through its lock waiters: timeout ladder, separate batch pool and runbook in [long-transactions.md](long-transactions.md).
