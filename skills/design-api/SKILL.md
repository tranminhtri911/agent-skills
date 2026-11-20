---
name: design-api
description: "Use when analyzing or changing an HTTP API, webhook or event contract, including payloads, pagination, errors, compatibility and endpoint idempotency. Triggers (vi): thêm API, sửa endpoint, request/response, webhook, phân trang API, mã lỗi."
metadata:
  version: "1.0.8"
  suite: devskills
---

# Design API

An API is a contract other code depends on. Describe it explicitly, validate and authorize on the server, keep backward compatibility, and make retried requests safe.

**Start from the project's base (CTX-009).** Match the existing endpoints: URL and naming style, request validation classes (serializer, FormRequest, DTO), auth/permission decorators or policies, error envelope, pagination shape, date/money formats. A new endpoint that answers differently from its neighbours breaks frontend helpers and generated clients. Enumerated fields are declared as `enum` in the schema from the backend enum, so clients get them generated instead of re-typing strings (CODE-011).

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Handler, service or job code behind the endpoint → **REQUIRED:** implement-backend.
- The endpoint reads or writes the database → **REQUIRED:** change-database.
- Authentication, permissions, tenants or user input → **REQUIRED:** review-security.
- Retries, webhooks, idempotency across systems → **REQUIRED:** design-reliability.

## Contract checklist

Endpoint/event name · request and response schema · auth and scopes · status and error codes · pagination/filter/sort · idempotency · timeout and rate limit · compatibility/versioning · synthetic examples · observability · side effects. Use OpenAPI in the version the framework and generators of the repo support (do not upgrade the spec version just because a newer one exists). Full checklist: [api-contract-checklist.md](references/api-contract-checklist.md).

## Rules

- API-001 the server validates and authorizes; never trust price, role, tenant or owner sent by the client.
- API-002 explicit request and response DTOs; never return ORM objects with internal fields or PII.
- API-003 distinguish omitted/null/empty/zero, especially in PATCH; block mass assignment of protected fields.
- API-004 stable error codes with correct HTTP semantics; never `200 OK` with a failure body.
- API-005 new APIs use one error shape, e.g. RFC 9457 Problem Details (`application/problem+json`): `type`, `title`, `status`, `detail`, `instance` plus a stable `code`. Keep existing APIs' shape for compatibility.
- API-006 pagination has a max limit and stable order (`created_at DESC, id DESC`); filter/sort fields come from an allowlist; prefer cursors for large tables.
- API-007 contract changes get a compatibility check and consumer tests; additive changes first, deprecation window before removal.
- API-008 money: amount in minor units or decimal string + currency + rounding rule; never binary floats.
- API-009 time: instants in UTC ISO-8601 with offset; date-only and business time zone are separate fields.
- API-010 size, rate and concurrency limits at the boundary (429 + `Retry-After`); batch endpoints count each item against limits.
- API-011 every new or changed endpoint ships with endpoint-specific request/response examples: method/URL, headers/auth, path/query/body fields and constraints, a reproducible local `curl`, success status/headers/body, applicable error cases, permissions and data/side effects. Document empty bodies explicitly; mark inapplicable cases with a reason. Examples use synthetic data, match the implemented contract and identify whether they are illustrative, schema-validated or locally verified. Missing examples leave the documentation requirement incomplete; a schema or generic error example alone is insufficient.

## Required endpoint examples (API-011)

Before handing over a new or changed endpoint, read [endpoint-examples.md](references/endpoint-examples.md) and fill its template in the project's existing API documentation/OpenAPI workflow. Cover each affected method/path, including preserved behavior when changing an endpoint. Keep examples beside the canonical contract and update them in the same change; do not create a competing documentation system. The reference includes an endpoint coverage table, a reusable template, a worked synthetic example and verification requirements. Never run mutation samples against a shared environment merely to document them.

## Patterns and verification

- API-011 automation: `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` (`api.examples`, required for API/API-spec changes; optional `contracts` extra). It checks every operation in the supplied contract for sample/input/response/error coverage, schema values, curl consistency and claimed local evidence. Missing/invalid entries fail; unsupported validation blocks. Manifest, static fixture, `run-tests --capture` evidence and support limits: [automatic-examples.md](references/automatic-examples.md). Review omitted routes, actual policy and business semantics separately; static validation never executes requests.
- Request/response, validation, object-level authorization, PATCH missing-vs-null, pagination, error envelope and frontend compatibility (DRF, Laravel): [api-patterns.md](references/api-patterns.md).
- Contract diff: export the spec, then `DS api-diff --spec docs/openapi.json --base-ref main --run <id>` (records `api.contract_diff`; breaking changes fail). Real responses against the spec (Schemathesis on 127.0.0.1), consumer typecheck, PATCH and pagination tests: [verification-api.md](references/verification-api.md).

## Idempotency (create order, charge, refund)

1. Client sends `Idempotency-Key` per business intent; scope = tenant + principal + operation.
2. Server atomically claims the key (UNIQUE constraint) with a request fingerprint, in the same transaction as the business write.
3. Same key + same payload → replay the stored response; same key + different payload → `409/422`; key still processing → `409` (retry later).
4. Authorization is re-checked before replaying; a key never grants access.
5. Retention covers the client's and provider's retry window; a business key (order number) protects beyond it.
6. Provider calls reuse a stable key and are reconciled when the outcome is unknown (design-reliability).

## Webhooks and events

Verify the signature on the raw body and the timestamp window · deduplicate by event id per provider/account · never assume ordering; apply valid state transitions or reconcile · acknowledge after durable receipt, process in a worker · store schema version and correlation id · test bad signature, replay, duplicate, out-of-order and crash cases (`ds.py simulate payment` can deliver signed duplicate/out-of-order webhooks).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `GET /orders?limit=100000` allowed | Enforce max limit; cursor pagination |
| Error detail strings parsed by clients | Stable `code` field; `detail` is for humans |
| Renaming a JSON field in place | Add the new field, deprecate, remove after consumers migrate |
| Disabling the submit button as the only duplicate protection | Server idempotency + unique constraint |
