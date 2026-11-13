# Database verification

| Need | Pass criterion |
| --- | --- |
| Same engine and version as production | tests run on the engine/version `inspect` found (compose image, settings), not SQLite for a Postgres app |
| Two concurrent transactions | two buyers of the last item: exactly one succeeds, stock never negative |
| Rollback at every step | a failure injected after step k leaves no partial rows for every k |
| Migration compatible with the running app | old code works on the new schema (expand phase) |
| Backfill resumable | stop it half-way, run it again: no row lost, none doubled |
| No N+1 | query count independent of row count |
| Models and migrations agree | `DS native-checks` → `native.migrations` (`makemigrations --check --dry-run`) passes |

Run with `DS run-tests --profile integration_isolated` (loopback network only); the preflight blocks remote/production database hosts.

## Engine fixture

- Django: test settings point at a disposable Postgres/MySQL (docker compose service on 127.0.0.1, `TEST: {"NAME": ...}`); match the major version of production.
- Laravel: `.env.testing` with a local MySQL/Postgres; `RefreshDatabase` for most tests, a truncating strategy for tests that need real commits.
- SQLite in-memory is acceptable only for pure unit tests that do not depend on locking, constraint or SQL dialect behaviour.

## Two concurrent transactions

```python
class LastItemRace(TransactionTestCase):  # real commits, not one wrapping transaction
    def test_only_one_buyer_wins(self):
        Product.objects.create(sku="A", stock=1)
        barrier, results = threading.Barrier(2), []

        def buy():
            try:
                barrier.wait()
                place_order(tenant_id=1, user_id=1, sku="A", quantity=1, idempotency_key=str(uuid4()))
                results.append("ok")
            except OutOfStock:
                results.append("out")
            finally:
                connection.close()  # each thread has its own connection; close it

        threads = [threading.Thread(target=buy) for _ in range(2)]
        [thread.start() for thread in threads]; [thread.join(10) for thread in threads]
        self.assertEqual(sorted(results), ["ok", "out"])
        self.assertEqual(Product.objects.get(sku="A").stock, 0)
```

Laravel: two processes (`Process::pool` or two `artisan tinker --execute` calls) against the test DB, or PHPUnit with two PDO connections.

## Rollback at every step

```python
@parameterized.expand(["after_stock", "after_order", "after_ledger"])
def test_failure_leaves_no_partial_state(self, step):
    def fail_at(name):
        if name == step:
            raise RuntimeError(f"injected failure {name}")

    with mock.patch("orders.services._checkpoint", side_effect=fail_at):
        with self.assertRaises(RuntimeError):
            place_order(...)
    self.assertEqual(Order.objects.count(), 0)
    self.assertEqual(Product.objects.get(sku="A").stock, 1)
```

The pattern: a hook (or mock on the next call) that raises after step k; assert every table is back to its starting state.

## Migration compatibility (expand → migrate → contract)

1. Expand: add nullable column/new table; the **old** application must keep working. Test: run the previous release's test suite (or key tests) against the migrated schema, or check out the old model code in a worktree and run it against the new DB.
2. Backfill in batches; switch reads/writes in code.
3. Contract (drop old column) only in a later release, after no code reads it.
4. Never rename a column in one step; never add a NOT NULL column without a default on a large table in one step.

## Backfill resume

```python
def test_backfill_resumes_without_loss_or_duplicates(self):
    make_rows(1000)
    with self.assertRaises(SimulatedCrash):
        backfill_totals(batch_size=100, crash_after_batches=3)
    backfill_totals(batch_size=100)  # second run resumes from the checkpoint
    self.assertEqual(Total.objects.count(), 1000)
    self.assertEqual(Total.objects.values("order_id").distinct().count(), 1000)
```

Make the backfill idempotent (upsert by natural key or `WHERE new_col IS NULL`) and commit the checkpoint with each batch.

## Query count

```python
def test_order_list_query_count_is_constant(self):
    make_orders(1)
    with self.assertNumQueries(4): self.client.get("/api/orders")
    make_orders(20)
    with self.assertNumQueries(4): self.client.get("/api/orders")
```
