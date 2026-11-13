# Backend verification: prove the rule holds on every path

| Need | Pass criterion |
| --- | --- |
| Business rule on every writer (API, admin, worker, import, command) | each path has a test that hits the rule |
| Retry / duplicate request | the same request (same idempotency key) twice creates one order |
| Crash after commit | a worker that dies after commit does not process the item twice |
| Failure mid-way | each step failing leaves no partial state (see change-database/verification-db.md) |

Primary evidence is the project's own tooling: `DS native-checks --execute --run <id>` (lint, typecheck, `manage.py check`, missing migrations), then `DS run-tests` with JUnit. `check-code` is a supporting signal only.

## 1. Find every writer, then test each

```bash
rg -n "Order\.objects\.(create|update|bulk_create)|\.save\(|Order::(create|update)" --type py --type php
rg -n "class .*Admin|@admin.register|management/commands|@shared_task|implements ShouldQueue" .
```

List them in the context map (`other_writers_of_same_tables`). A rule enforced only in the serializer is skipped by admin, imports and tasks: move it into the use case and test each entry point against it.

```python
class StockRuleOnEveryPath(TestCase):
    def test_api(self):        self.assert_rejected(lambda: self.client.post("/api/orders", {...}))
    def test_admin(self):      self.assert_rejected(lambda: self.admin_client.post(admin_add_url, {...}))
    def test_import(self):     self.assert_rejected(lambda: call_command("import_orders", fixture_csv))
    def test_worker(self):     self.assert_rejected(lambda: process_order_task.apply(args=[payload_id]))
```

## 2. Retry and duplicate requests

```python
def test_same_idempotency_key_creates_one_order(self):
    headers = {"HTTP_IDEMPOTENCY_KEY": "k-1"}
    first = self.client.post("/api/orders", body, content_type="application/json", **headers)
    second = self.client.post("/api/orders", body, content_type="application/json", **headers)
    self.assertEqual(first.json()["id"], second.json()["id"])
    self.assertEqual(Order.objects.filter(idempotency_key="k-1").count(), 1)
```

Concurrent duplicates need a real DB and two connections (`TransactionTestCase` + threads, or two processes); a unique constraint on `(tenant_id, idempotency_key)` is the real guard — test that the loser returns the winner's result, not a 500.

## 3. Crash after commit / redelivery

- Outbox or `on_commit`: assert nothing was sent when the transaction rolls back (`captureOnCommitCallbacks` in Django ≥ 3.2).
- Redelivery: run the task twice with the same message; assert one side effect (dedup marker committed with the work).
- Simulated crash: raise after the commit inside the task, re-run it, assert the item is not processed again.

```python
def test_rollback_sends_no_email(self):
    with self.captureOnCommitCallbacks(execute=True) as callbacks:
        with self.assertRaises(OutOfStock):
            place_order(..., quantity=999)
    self.assertEqual(callbacks, [])

def test_task_redelivery_is_idempotent(self):
    process_payment_result.apply(args=[event_id]); process_payment_result.apply(args=[event_id])
    self.assertEqual(LedgerEntry.objects.filter(event_id=event_id).count(), 1)
```

Laravel: `Queue::fake()` / `Bus::fake()` to assert dispatch, `DB::afterCommit` behaviour with `RefreshDatabase` vs `DatabaseTransactions` (the latter never commits — use a truncating strategy for after-commit tests).

## 4. Errors and resources

- Each mapped domain error has a test for its status code and envelope; an unexpected exception returns 500 without internals.
- External calls are tested against the simulator or a fake with timeout/5xx/slow scenarios, never the real provider (test-safely).
- `run-tests` reports leftover child processes; treat that as a leak to fix.
