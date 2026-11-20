---
name: implement-backend
description: "Use when analyzing or implementing server-side logic, including handlers, services, jobs, uploads and external clients. Triggers (vi): backend, xử lý nghiệp vụ, controller, service, job nền, batch, upload file."
metadata:
  version: "1.0.8"
  suite: devskills
---

# Implement Backend

Follow the existing module layout and framework conventions, and make every request or job follow one explicit path: validate → authenticate → authorize → use case → transaction/side effects → response.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

**Start from the project's base (CTX-009).** Open the reference module of the same kind and the project-owned bases/helpers that `inspect` lists under "Project conventions" — base model/controller/viewset, permission or auth decorators, error classes and handler, response envelope, pagination class, service/repository bases, logging and transaction helpers — and build the new module the same way. Extend a base that lacks something instead of writing a parallel one. Statuses, types, roles, limits and external URLs come from the project's enums, constants and settings — `OrderStatus.PAID`, `BookingStatus::CONFIRMED`, `settings.X` — never re-typed literals (CODE-011, write-maintainable-code).

## Hand-offs — load these too when the condition holds

Backend work almost always crosses another skill's area. Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Any query, repository, ORM model, stored procedure, transaction, lock or delete → **REQUIRED:** change-database.
- A new or changed endpoint, request/response or error format → **REQUIRED:** design-api.
- External calls, retries, jobs or batches that must not run twice or die halfway → **REQUIRED:** design-reliability.
- Workers, thread pools, async, loops over many rows → **REQUIRED:** review-performance.
- Auth, permissions, tenants, uploads, user input → **REQUIRED:** review-security.
- Writing or running tests → **REQUIRED:** test-safely.

## Module layout (default; follow the repo when it differs)

```
backend/features/orders/
  router.py        # HTTP routes + dependency injection (controller in MVC frameworks)
  schemas.py       # request/response DTOs and validation
  service.py       # use cases: create_order, cancel_order (transaction owner)
  repository.py    # queries/persistence with domain meaning
  models.py        # ORM mapping
  policies.py      # permission/business policies reused by several use cases
  tests/
```

The layout above is a fallback: the source's own layers (`patterns in use` in `inspect`, e.g. Controller → FormRequest → Service, or views → `services.py`/`selectors.py`) win, and no layer is added that only forwards calls (DES-007). Create only folders that have a real responsibility; a small endpoint can live in the feature router. `shared/` holds only truly shared code. No dependency cycles between features: call another feature through its public service (ARC-003). Framework-specific notes: [framework-adapters.md](references/framework-adapters.md).

## Request/job rules

- BE-001 validate shape, type, range, business rules and cross-field relations at the boundary.
- BE-002 use cases have explicit inputs/outputs, an error model and own the transaction (repositories never commit mid-use-case, ARC-005).
- BE-003 every remote call has a timeout/deadline; classify errors; never return raw provider errors.
- BE-004 every resource has an owner and cleanup: sessions, HTTP clients, files, streams, temp dirs.
- BE-005 retryable operations are idempotent; prevent races with atomic writes/unique constraints (design-api, change-database).
- BE-006 swap real providers for simulators through dependency injection, not `if testing` branches.
- BE-007 important jobs survive restarts: durable queue/state, not fire-and-forget threads in the web process.
- BE-008 honour cancellation and graceful shutdown: stop intake, drain with a deadline, checkpoint, release resources.
- BE-009 the same invariant holds on every entry path: API, admin, cron, imports, workers.
- BE-010 inject clock, ID generator and randomness so tests are deterministic.
- BE-011 a status with rules changes only through one transition function or the project's state library: allowed moves declared once, guard + side fields + after-commit effects inside, every writer calls it: [state-transitions.md](references/state-transitions.md).
- SEC-001 authorization is checked on the server for the specific object/tenant, not only in the router or UI.

## Batch and background jobs

Each job: `job_id`, attempt id, idempotency scope, cursor/checkpoint committed with the work, per-item failure policy, expected total, resource limits. Process in chunks with one transaction per chunk/item, never one transaction for millions of rows. Use claims/leases with dedup; a lease can expire while the old worker runs, so guard writes with version checks. Failed items go to a dead-letter state with a replay path that does not duplicate effects. Patterns: [jobs-and-batches.md](references/jobs-and-batches.md).

## Files and external input

Limit upload size and decompressed size, check real content type, generate server-side file names, block path traversal and symlink escapes, stream large files, verify checksums when needed. Never send customer files to outside services to debug.

## Verify

For every new or changed HTTP endpoint, complete API-011 documentation: endpoint-specific invocation/`curl`, field constraints, success/error samples, required permissions, changed/preserved data and verification status. Use the project's canonical API docs; when design-api is available, follow its `references/endpoint-examples.md`. Check actual route/schema/policy/service behavior rather than copying a generic example, and leave missing required evidence unverified.

Run `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` (contracts extra) for the `api.examples` roster check. Missing/invalid samples fail and unsupported validation blocks. Claim local execution only with exact passing current-run test identity and an observed exchange fingerprinted by `run-tests --capture`; see design-api `references/automatic-examples.md` when available. Review route/export completeness and actual policies/data effects separately.

`DS native-checks --execute --run <id>` runs the project's own linter, type checker, build and framework checks (primary evidence; `check-code` is a supporting layer). Then `DS check-code` (blocking calls in async handlers, missing timeouts, engine-per-request, SQL string building, swallowed exceptions…), then test-safely for tests and review-security for trust boundaries. External providers in tests: `DS simulate payment` (design-reliability, test-safely).

Prove the rule on every writer (API, admin, worker, import), duplicate requests and crash-after-commit: [verification-backend.md](references/verification-backend.md). Layering, transactions, concurrency and errors with Django/DRF and Laravel examples: [backend-patterns.md](references/backend-patterns.md).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Business logic duplicated across entry points | Reuse the project’s existing policy/use-case location; add a layer only when it solves a concrete problem |
| `requests.get(url)` without timeout | `timeout=(3, 10)`; one retry owner |
| Calling the payment API inside the DB transaction | Commit state + outbox, call the provider from a worker |
| `asyncio.create_task(...)` and forget | Durable queue for important work; TaskGroup for request-scoped work |
| Different validation in admin import | Reuse the same use case/policy |
| Editing the big calculator for one new rule | New pricing unit + selector by effective date/flag; old path unchanged and pinned (CHG-002) |
| `$booking->status = 'cancelled'` in several controllers | One transition function/enum `allowedNext()` used by every writer (BE-011) |
