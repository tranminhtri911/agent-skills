# Jobs and batches that survive crashes and retries

## Checkpointed chunk loop

```python
def run_backfill(job: Job, session_factory, chunk_size: int = 500) -> None:
    """Process rows after job.cursor in chunks; each chunk commits work and cursor together."""
    while True:
        with session_factory() as session, session.begin():
            rows = repository.next_chunk(session, after_id=job.cursor, limit=chunk_size)
            if not rows:
                job_repository.mark_done(session, job.id)
                return
            for row in rows:
                process_item(session, row)  # idempotent: safe if the chunk is replayed
            # The cursor moves in the same transaction as the work, so a crash
            # never skips rows and a replay never applies a chunk twice.
            job_repository.save_cursor(session, job.id, rows[-1].id)
        throttle.wait()  # protect the database and other traffic
```

Rules: no single transaction for the whole table; per-chunk timeouts; stop conditions (error rate, lag, time window); totals before/after recorded; dry-run mode that performs no writes (and no writes in constructors/startup).

## Claim / lease with fencing

```sql
/* Claim one job atomically; SKIP LOCKED lets several workers share the queue. */
UPDATE jobs
SET status = 'running', lease_until = now() + interval '5 minutes', lease_version = lease_version + 1
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'queued' OR (status = 'running' AND lease_until < now())
  ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING id, lease_version;
```

When writing results, check `lease_version` so a worker whose lease expired cannot overwrite a newer attempt.

## Dead letters and replay

Items failing after N attempts move to `failed` with the error code and attempt count. Replay re-enqueues with the **same** idempotency key; effects already applied are recognised through the dedup table and not repeated.

## Testing a batch (with test-safely)

- Fail at item N, then resume: final counts equal the expected total, no duplicates.
- Crash after commit, before acknowledging: replay does not double-apply.
- Two workers at once: each item processed exactly once in effect.
- Queue overload: backpressure or rejection, never silent drops.
