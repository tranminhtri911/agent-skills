# Queries, ORM, N+1, lost updates and transaction scope

## N+1 queries

Symptom: one query for the list, then one per row for a relation.

| Stack | Fix | Guard in tests |
| --- | --- | --- |
| Django | `select_related("customer")` (FK/one-to-one, JOIN), `prefetch_related("items")` (reverse/M2M, second query), `Prefetch(queryset=…)` to filter, `.only()` for wide tables | `with self.assertNumQueries(3):` around the view/serializer call |
| DRF | do it in `get_queryset()`, not in the serializer; `SerializerMethodField` that queries per row is N+1 | same, with 1 row and with 20 rows: the count must not grow |
| Laravel | `with('customer', 'items')`, `withCount('items')`, `load()` after the fact | `Model::preventLazyLoading(! app()->isProduction())` in `AppServiceProvider`; `DB::enableQueryLog()` count |
| EF6 | `.Include(x => x.Items)`, projection with `Select` | log SQL (`Database.Log`) in an integration test |

Assert the query count does not depend on the number of rows: run the same test with 1 and 20 rows.

## Lost updates (read-modify-write)

```python
# Wrong: two requests read 10, both write 9.
product = Product.objects.get(pk=pk); product.stock -= 1; product.save()

# Right, single statement:
Product.objects.filter(pk=pk, stock__gte=1).update(stock=F("stock") - 1)

# Right, when the rule needs the row in Python: lock it inside the transaction.
with transaction.atomic():
    product = Product.objects.select_for_update().get(pk=pk)
    ...

# Right, for long user edits (form open for minutes): optimistic version column.
updated = Document.objects.filter(pk=pk, version=client_version).update(body=body, version=F("version") + 1)
if not updated:
    raise EditConflict()  # 409 to the client, which reloads and merges
```

Laravel: `->decrement('stock')`, `lockForUpdate()` inside `DB::transaction`, or `where('version', $v)->update([... 'version' => DB::raw('version + 1')])`.

`save()` without `update_fields` writes every column and can overwrite a concurrent change to another column: use `save(update_fields=[...])`.

## Transaction scope

| Mistake | Effect | Fix |
| --- | --- | --- |
| HTTP/payment/email call inside the transaction | locks held for seconds; side effect not undone on rollback | outbox / `on_commit` / `afterCommit` |
| One transaction per row in a multi-step write | partial state on failure | one `atomic()` around the business unit |
| One transaction around a million-row batch | huge locks, long rollback, replication lag | chunks of N rows, checkpoint committed with each chunk |
| Reading outside, writing inside, deciding on the stale read | check-then-act race | re-read with lock, or conditional `UPDATE … WHERE` |
| Catching DB errors inside `atomic()` and continuing | Postgres: "current transaction is aborted" | nested `atomic()` (savepoint) around the risky statement, or handle outside |

Isolation: Postgres/MySQL default (READ COMMITTED / REPEATABLE READ) does not prevent write skew; use a constraint, a lock or SERIALIZABLE with retry when two rows together must satisfy a rule.

## Indexes from real queries

1. Take the query the ORM actually emits (`str(queryset.query)`, Django Debug Toolbar, `->toSql()`, `DB::listen`).
2. `EXPLAIN (ANALYZE, BUFFERS)` on an isolated DB with realistic row counts (never on production without approval).
3. Composite index column order: equality filters first (tenant_id), then range/sort (`created_at`), matching `ORDER BY`. Cover the tenant column in every multi-tenant index.
4. Every index costs writes: remove ones no query uses; create large indexes concurrently (`CREATE INDEX CONCURRENTLY`, Django `AddIndexConcurrently` with `atomic = False`).

## Query plans safely per engine (IDX-008, IDX-009)

Before any connection, query, plan inspection or statistics update on a non-local database, follow dev-orchestrate OPS-012: warn with the exact commands, server/environment, database, purpose and risks, then wait for explicit approval. This includes estimated plans and read-only accounts on dev/STG/production or any other remote/shared DB, including through localhost tunnels. The examples below explain execution effects; they do not grant access. Review already-provided plans offline or use a confirmed local disposable DB while waiting.

Read the plan of the SQL the application really sends (ORM output, EF Core `ToQueryString()`, the stored procedure body with representative parameters), on synthetic data sized like production. Statistics must be current (`ANALYZE`, `UPDATE STATISTICS`) or the plan lies.

| Engine | Estimated plan — does not execute | Actual plan — **executes the statement** |
| --- | --- | --- |
| PostgreSQL | `EXPLAIN (FORMAT TEXT) <stmt>` | `EXPLAIN (ANALYZE, BUFFERS) <stmt>`; for DML: `BEGIN; EXPLAIN ANALYZE <dml>; ROLLBACK;` (rows locked until the rollback) |
| MySQL 8 | `EXPLAIN FORMAT=TREE <stmt>` | `EXPLAIN ANALYZE <stmt>` (SELECT, multi-table UPDATE/DELETE; always TREE format) |
| SQL Server | `SET SHOWPLAN_XML ON; <stmt>; SET SHOWPLAN_XML OFF;` (SSMS: Display Estimated Execution Plan) | `SET STATISTICS XML ON; SET STATISTICS IO, TIME ON; <stmt>` (SSMS: Include Actual Execution Plan); for DML wrap in `BEGIN TRAN … ROLLBACK` on an isolated DB only |
| Oracle | `EXPLAIN PLAN FOR <stmt>; SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);` (writes `PLAN_TABLE`) | `/*+ GATHER_PLAN_STATISTICS */` + `DBMS_XPLAN.DISPLAY_CURSOR(format => 'ALLSTATS LAST')` |
| SQLite | `EXPLAIN QUERY PLAN <stmt>` | — (time the statement on a copy) |

What to look for, by symptom:

| Plan shows | Usually means | Typical fix |
| --- | --- | --- |
| Seq Scan / Table Scan / Clustered Index Scan on a large table | no usable index, or a non-sargable predicate (`WHERE YEAR(created_at) = …`, `LIKE '%x'`, function on the column) | index that matches the predicate; rewrite as a range |
| Estimated rows far from actual (10×+) | stale statistics, skewed data, parameter sniffing | refresh statistics; test with skewed parameters; consider plan guides/recompile only with evidence |
| Key Lookup / RID Lookup per row, Nested Loop over many rows | index missing the selected or filtered columns | covering index (`INCLUDE`) or select fewer columns |
| Sort / Hash with spill warnings, large memory grant | sorting/joining more rows than needed | index in `ORDER BY` order, filter earlier, keyset pagination |
| `CONVERT_IMPLICIT` (SQL Server), type cast on the column (PostgreSQL) | parameter type differs from the column type | parameter typed like the column (`varchar` vs `nvarchar`, int vs bigint) |
| Bulk DELETE/UPDATE touching many rows, lock escalation | one huge statement holding locks | chunks of N rows by key with a commit per chunk (TX rules, [long-transactions.md](long-transactions.md)) |

Record in the spec or report: statement, engine/version, row counts, estimated vs actual rows, index used, duration, and where it ran. An estimated plan read on a shared server is evidence of the access path only; timing claims need an actual plan on an isolated copy.

## Pagination queries

Offset pagination skips/duplicates rows when data changes between pages and gets slower with depth. Use keyset (cursor) pagination on a unique, stable sort: `WHERE (created_at, id) < (:last_created_at, :last_id) ORDER BY created_at DESC, id DESC LIMIT :n` with an index on `(tenant_id, created_at, id)`.
