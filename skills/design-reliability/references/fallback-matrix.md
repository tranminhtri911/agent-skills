# Fallback matrix (plan §22.2)

| Failure | Default action | Forbidden |
| --- | --- | --- |
| Read-only external API timeout | Bounded retry; stale data only if the contract allows and the age is shown | Presenting stale data as current |
| Payment response lost | `pending/unknown` → reconcile by operation key | Charging again with a new key |
| DB commit outcome unknown | Look up the operation/business key in the authoritative store | Assuming it rolled back |
| Deadlock already rolled back | Retry the whole safe unit within budget | Infinite retry, repeating external effects |
| Pool exhausted | Timeout/backpressure, shed load, investigate leaks | Opening unlimited connections |
| Cache down | Read DB within capacity; shed when needed | Sending all traffic to the DB unbounded |
| Auth/permission service unavailable | Deny, or designed cached authorization with TTL | Allow-all or permanent stale permissions |
| Queue full | Backpressure, reject, or persist as pending | Dropping the job and reporting success |
| Worker dies mid-batch | Resume from checkpoint + dedup + invariant check | Re-running the whole batch with new effects |
| Browser not installed | Run the other checks; visual = BLOCKED | Fake or reused screenshots |
| Linter/scanner infrastructure error | `blocked`, bounded retry, or verified equivalent tool | Exit 0 or silently skipped gate |
| Baseline missing | Candidate + `NEEDS_BASELINE` | Auto-approving a baseline |
| Migration breaks old app | Stop rollout; roll forward/back based on evidence | Assuming code revert is enough |
| Sandbox safety unproven | Block network/effects; use the offline simulator | "Just once" against production |
| Agent out of context/budget | Save a valid checkpoint; report done vs missing | Inventing results |

## Retry helper (Python)

```python
def call_with_retry(operation, *, attempts: int = 3, base_delay_seconds: float = 0.2, deadline_seconds: float = 10.0):
    """Retry only transient failures with exponential backoff + jitter inside an overall deadline."""
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except TransientError as error:
            elapsed = time.monotonic() - started
            delay = min(error.retry_after or base_delay_seconds * 2 ** (attempt - 1), 5.0) * random.uniform(0.5, 1.5)
            if attempt == attempts or elapsed + delay > deadline_seconds:
                raise
            time.sleep(delay)
```

## Outbox consumer (pseudo)

```
loop:
  claim N outbox rows (FOR UPDATE SKIP LOCKED / lease)
  for each row:
    result = provider.call(row.payload, idempotency_key=row.operation_key, timeout=...)
    in one transaction: apply result to business state + mark row done + store dedup marker
    on timeout: mark row pending_reconciliation (do not retry blindly)
```
