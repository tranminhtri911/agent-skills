# Operability: trace it, measure it, know when to stop and how to recover

| Need | Pass criterion |
| --- | --- |
| Correlation id across request → job → provider | one id follows an action from the API log to the worker log and the outbound call |
| Metrics | error rate, latency (p95), queue lag/backlog and business counters exist for the changed flow |
| Rollout stop conditions | written thresholds that mean "stop / roll back" |
| Recovery guide | steps to detect, stop, repair data and replay, tested at least once in a local/staging setting |

## Correlation id

Accept `X-Request-ID` (or `traceparent`) if present and valid, otherwise generate one; return it in the response and in error bodies; put it in every log line and in job payloads.

```python
# Django middleware (use the project's logging setup; contextvars works with threads and async)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

class RequestIdMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if re.fullmatch(r"[A-Za-z0-9\-]{8,64}", incoming) else uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)

# Celery: pass it explicitly and restore it in the task.
process_order.apply_async(args=[order_id], headers={"request_id": request_id_var.get()})
```

Laravel: `Context::add('request_id', $id)` (Laravel 11+) propagates into queued jobs and logs; older versions: `Log::withContext([...])` in middleware + a job property.

Frontend: show the correlation id in error UI ("Error code c-123") so support can find the logs.

## Metrics for the changed flow

- RED per endpoint/job: **R**ate, **E**rrors, **D**uration (p50/p95/p99).
- Queues: backlog size, age of oldest message (lag), retries, dead-letter count.
- Business: orders created, payments pending reconciliation, emails failed — the numbers that tell you users are affected.
- Use the project's existing stack (Sentry, Prometheus, CloudWatch, Datadog, Application Insights); do not add a new one for one feature.

## Rollout stop conditions (write them before release)

```
Feature flag: orders.new_checkout (default off; enable 5% → 25% → 100%)
Stop and turn the flag off when, for 10 minutes compared with the previous week:
  - 5xx rate on POST /orders > 1% or 2× baseline
  - p95 latency of POST /orders > 800 ms
  - payments in pending_reconciliation > 20 or older than 15 minutes
  - checkout dead-letter queue > 0
Owner: <name>; dashboard: <link>; alert: <channel>
```

## Recovery guide (runbook) template

1. **Detect**: which alert/metric/log query shows the problem; example correlation id search.
2. **Stop the damage**: flag off / pause consumer / scale worker to 0 — exact commands, who may run them (respect the authorized environment and effect).
3. **Assess**: queries that list affected records (read-only), expected counts.
4. **Repair**: idempotent script or replay from outbox/dead-letter by key; dry-run first, then apply within the user's authorization; in-scope local repairs need no extra confirmation.
5. **Verify**: counts and invariants after repair (e.g. one successful charge per order).
6. **Follow-up**: root cause, regression test, tighter alert.

Store it in `docs/runbooks/<feature>.md` (or the project's existing location) and link it from the decision memo.
