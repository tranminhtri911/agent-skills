---
name: design-reliability
description: "Use when designing, reviewing or adding retries, timeouts, fallbacks, queues, an outbox, compensation or rollback across several systems (database plus payment, email, storage or external APIs), jobs that must not run twice or die halfway, or partial failures. Triggers (vi): thử lại, timeout, mất kết nối, gọi dịch vụ ngoài, thanh toán, email/SMS/thông báo, đồng bộ, sao lưu lên Google Drive/cloud, job chạy trùng hoặc chết giữa chừng. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.5"
  suite: devskills
---

# Design Reliability

Failures are normal: design what happens on timeout, duplicate, partial completion and unknown outcome — without ever weakening auth, integrity or data isolation, and without hiding the failure.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Transactions, row/advisory locks, outbox or idempotency tables → **REQUIRED:** change-database.
- Proving failure paths with simulators or fault injection → **REQUIRED:** test-safely.
- Queues, workers, pools or timeouts under load → **REQUIRED:** review-performance.

## Rules (REL-001…REL-009)

- Retries: bounded count, exponential backoff with jitter, respect `Retry-After`, overall deadline. Retry only transient errors and operations that are safe to repeat (idempotent or keyed).
- One layer owns retries (client × service × worker multiplies: 3 × 3 × 3 = 27 calls).
- Unknown outcome (payment or commit timed out) → reconcile by operation identity; never repeat with a new identity.
- Circuit breaker, bulkhead and backpressure when a dependency can drag the system down; expose metrics and a limited recovery probe.
- Compensation has its own identity, state and retries; never delete the history of the original action.
- Keep the original error and partial state; never fake success with mock data in production.
- Fallbacks never relax authentication, authorization, signature/TLS checks or tenant isolation.
- Every critical flow has a runbook: detect, mitigate, recover, verify invariants, close.

## Timeouts

Every remote call has connect + read timeouts and an overall deadline that is shorter than the caller's. Typical starting points: connect 2-3 s, read 5-10 s for interactive calls; background jobs longer but always bounded.

## Multi-system steps (no distributed rollback)

DB transaction writes business state + outbox → worker calls the provider with a stable idempotency key → result + dedup marker committed together → timeout = `pending_reconciliation` → reconciler resolves by key → compensation (release reservation, refund) by policy. A DB rollback cannot un-send an email or un-charge a card. Patterns and the fallback matrix: [fallback-matrix.md](references/fallback-matrix.md).

## Verify with the simulator (no real provider)

Start: `DS simulate payment --port 8787 --delay-seconds 2` (run it in the background; it binds to 127.0.0.1). Scenarios per request (`X-Sim-Scenario` header or `scenario` field): `success`, `decline`, `success_then_timeout`, `timeout_before_processing`, `server_error`, `rate_limited`, `pending`, `slow_processing`. Signed webhooks can be delivered normally, duplicated or out of order to your local endpoint. Test that:

- `success_then_timeout` + retry with the same key → exactly one charge;
- `slow_processing` + concurrent retry → `409 in_progress`, one charge;
- duplicate and out-of-order webhooks → state applied once, valid transitions only;
- worker crash after commit → outbox resumes, no lost or doubled effect.

API reference: [simulator-api.md](references/simulator-api.md).

## Operability

Correlation id from request to job to provider, RED and queue-lag metrics, written rollout stop conditions and a recovery runbook: [operability.md](references/operability.md).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `except Exception: return default` around a payment call | Classify the error; unknown → pending + reconcile |
| New idempotency key on each retry | Key per business intent, reused by every retry |
| Auth service down → allow all | Deny, or a designed cached decision with TTL |
| Retrying validation errors | Only transient errors (timeouts, 429, 503) |
| Cache down → all traffic to DB unbounded | Shed load or limit concurrency to the DB |
