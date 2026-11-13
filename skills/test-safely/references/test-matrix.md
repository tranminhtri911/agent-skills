# Test matrix by situation (plan §19.2)

| Situation | Focus | Success evidence |
| --- | --- | --- |
| Null/empty/zero/negative/over-limit input | unit + schema | rejected/accepted per contract |
| Unicode, long text, i18n | unit + UI | no wrong truncation, layout intact |
| Other role/tenant | authz integration | no object/field/count leaked |
| Duplicate create | concurrent integration | one business object/effect |
| Same idempotency key, different payload | API integration | conflict, original data unchanged |
| Crash after commit, before response | idempotency restart test | retry finds the durable result |
| Replay after permission revoked | authz + idempotency | no cached response leaked |
| Two buyers, last item | DB concurrency (real engine) | total reserved ≤ stock |
| Step 2 of 3 fails | DB integration | all atomic changes rolled back |
| Deadlock/serialization failure | isolated fault injection | bounded retry, correct outcome |
| Provider success then timeout | simulator `success_then_timeout` | pending/reconcile, one charge |
| Duplicate/out-of-order webhook | simulator delivery modes | event applied once, valid transitions |
| Invalid webhook signature | negative integration | no business effect |
| Worker crash after commit | restart test | outbox resumes, no lost/doubled effect |
| Batch crash midway | job test | resume from checkpoint, no duplicates |
| Queue overload | bounded load | backpressure/rejection per policy |
| Pool exhausted | integration fault | clear timeout, recovery |
| Request cancelled | lifecycle test | resources cleaned, no orphan task |
| Route change during fetch (UI) | component/E2E | stale result not rendered |
| Loading/error/empty UI | E2E + visual | behavior and screenshot per state |
| Wrapping, responsive reflow, added rows/items | E2E + rendered layout inspection | long content and enough items at target/transition widths; no unintended overflow, overlap or clipping; logical row placement, alignment and spacing; inspected screenshots recorded |
| Unusual UI or mismatch with product/users/business flow | E2E + contextual UX review | evidence and user impact recorded against established roles, tasks and business rules; confirmed defects, concerns needing confirmation and optional improvements distinguished even when tests pass |
| Keyboard-only user | a11y/E2E | focus and labels correct |
| API/schema incompatible | contract diff | breaking change detected |
| Old app + expanded schema | migration compatibility | old flow keeps working |
| Repeated workload | soak (performance_isolated) | resources stay within budget |
| Production credential by mistake | runner safety | blocked before the first request |
| Missing tool/browser | capability check | reported blocked |

## Examples

```python
# Real DB concurrency: two sessions race for the last item (integration_isolated).
def test_last_item_cannot_be_sold_twice(engine, product_with_stock_1):
    def buy() -> bool:
        with Session(engine) as session, session.begin():
            return inventory.try_reserve(session, product_with_stock_1.sku, quantity=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: buy(), range(2)))
    assert sorted(results) == [False, True]
```

```python
# Payment via the simulator: lost response + retry must not double charge.
def test_retry_after_lost_response_charges_once(payment_client):
    key = "order-42-payment"
    with pytest.raises(GatewayTimeout):
        payment_client.charge(125000, "VND", key=key, scenario="success_then_timeout")
    assert payment_client.charge(125000, "VND", key=key).status == "succeeded"
    assert len(payment_client.lookup(key)) == 1
```

```python
# Batch: fail at item 3, resume, totals exact.
def test_backfill_resumes_without_duplicates(db, job):
    with pytest.raises(InjectedFailure):
        run_backfill(job, fail_at_item=3)
    run_backfill(job)
    assert db.count_processed() == db.count_source() and db.count_duplicates() == 0
```
