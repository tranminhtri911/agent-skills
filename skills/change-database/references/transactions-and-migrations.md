# Transactions, concurrency and migrations

## Atomic multi-step write with automatic rollback

```python
def place_order(session_factory, command: PlaceOrder) -> int:
    """All steps commit together or not at all; any exception rolls everything back."""
    with session_factory() as session, session.begin():
        order_id = orders.insert(session, command)
        affected = session.execute(
            text("UPDATE inventory SET available = available - :qty "
                 "WHERE tenant_id = :tenant AND sku = :sku AND available >= :qty"),
            {"qty": command.quantity, "tenant": command.tenant_id, "sku": command.sku},
        ).rowcount
        if affected != 1:
            raise OutOfStockError(command.sku)  # triggers rollback of the order insert too
        outbox.add(session, "order.placed", {"order_id": order_id})
    return order_id
```

## Choosing a concurrency control

| Need | Tool |
| --- | --- |
| Decrement without going negative | Conditional `UPDATE … WHERE qty >= :n`, check affected rows |
| Edit form overwritten by another user | `version` column: `UPDATE … SET …, version = version + 1 WHERE id = :id AND version = :v` |
| Several rows must stay consistent | `SELECT … FOR UPDATE` in a consistent order, short transaction |
| Complex invariants across rows | SERIALIZABLE isolation + bounded retry of the whole unit |
| One-at-a-time per business key | UNIQUE constraint or advisory lock per key |

Lock timeout and deadlock monitoring stay on (TX-005). Retry only after a confirmed rollback (TX-006); unknown commit outcome → look up by operation id (TX-007).

## Multi-system flow (DB + provider + notification)

1. Transaction: business state + outbox row.
2. Worker claims outbox rows, calls the provider with a stable idempotency key.
3. Result stored with a dedup marker in the same transaction as the business update.
4. Timeout/unknown → `pending_reconciliation`; reconciler asks the provider by key.
5. Compensation (release stock, refund) has its own identity and retries; history is never deleted.

## Migration phases (expand/contract)

| Phase | Example: rename `name` → `full_name` |
| --- | --- |
| Expand | add nullable `full_name`; app writes both |
| Backfill | chunked copy with checkpoint and throttling |
| Switch | app reads `full_name`; verify counts/invariants |
| Contract | after all app versions are updated, drop `name` (shared environments require authorization; in-scope local work proceeds directly) |

Per migration record: lock impact, estimated duration on production-like volume, stop condition, verification query, recovery (roll forward or restore). Test with the same engine/version (container) and synthetic data; record row counts before/after.
