# API contract checklist

## Endpoint

- [ ] Method and path follow existing conventions (plural resources, kebab/snake case as in the repo).
- [ ] Auth: who may call it; object-level check (tenant/owner) inside the use case.
- [ ] Request schema: required/optional fields, types, ranges, formats, max lengths, max array sizes; unknown fields rejected or ignored by explicit policy.
- [ ] Response schema: only public fields; stable types; no internal ids/PII unless required.
- [ ] Status codes: 200/201/202/204 success; 400 malformed; 401 unauthenticated; 403 forbidden; 404 not found (also for objects of other tenants); 409 conflict/idempotency; 422 validation; 429 rate limited (+`Retry-After`); 5xx only for server faults.
- [ ] Error body: one shape (Problem Details + `code`), no stack traces or SQL.
- [ ] Pagination: `limit` (default, max), cursor or page, stable sort, total count only if cheap.
- [ ] Filtering/sorting: allowlisted fields and operators.
- [ ] Idempotency: required for create/charge/refund; key scope, retention, conflict behaviour.
- [ ] Timeouts and rate limits documented; long work returns 202 + status endpoint.
- [ ] Side effects listed (emails, payments, events); none happen before validation/authorization succeed.
- [ ] Versioning and deprecation policy; compatibility with old clients/app versions during rollout.
- [ ] Observability: request id/trace id in logs and responses; metrics for errors and latency.
- [ ] API-011: every new/changed method + path has its own documentation and sample coverage row; do not rely on generic examples shared by the whole API.
- [ ] Invocation: method, local base URL, path/query parameters, required headers, authentication scheme and required role/scopes/tenant/owner rules; reproducible `curl` with synthetic fixtures and placeholder credentials.
- [ ] Inputs: field location, type, required/optional/conditional status, nullability, default or omission behavior, constraints and concrete sample value; bodyless requests say so.
- [ ] Success: exact status, relevant headers and body; a 204/bodyless response explicitly has no JSON body. Cover distinct success shapes, empty lists and pagination where applicable.
- [ ] Errors: sample trigger/request variation, exact status/headers/body and stable code for every documented applicable failure; cover authentication, authorization, validation, missing objects, conflicts, rate limits and other implemented failures. Explain cases that do not apply; do not invent unsupported statuses.
- [ ] Business/data effects: what changes, what must stay unchanged, external effects, transaction boundary, replay/retry behavior and any asynchronous completion/status endpoint.
- [ ] Examples contain synthetic data only and match actual route/schema/validation/policy/error-handling code; distinguish illustrative examples from schema validation and captured local execution evidence.
- [ ] A coverage review links method/path → documentation/example → source/schema → applicable scenario → test or review evidence. Missing sections or unexecuted required checks remain incomplete/unverified.

Template, completed example and evidence rules: [endpoint-examples.md](endpoint-examples.md).

- [ ] `DS api-examples --spec <exported-contract> --file <sample-manifest> --run <id>` passes for the full reviewed contract scope (`api.examples`). Unsupported cases remain blocked. A local-execution claim links an exact passing current-run testcase and a runner-fingerprinted capture; see [automatic-examples.md](automatic-examples.md).

## Problem Details example

```json
{
  "type": "https://docs.example.invalid/errors/out-of-stock",
  "title": "Out of stock",
  "status": 409,
  "code": "OUT_OF_STOCK",
  "detail": "SKU A-100 has 0 units available.",
  "instance": "/orders/req_7f3a"
}
```

## Money and time fields

```json
{ "total": { "amount_minor": 125000, "currency": "VND" }, "created_at": "2026-10-28T03:15:00Z", "delivery_date": "2026-11-02" }
```

## Breaking vs non-breaking

| Change | Breaking? |
| --- | --- |
| Add optional request field / response field | No (clients must ignore unknown fields) |
| Add required request field | Yes |
| Rename/remove field, change type or meaning | Yes |
| New enum value in response | Often yes for strict clients — announce it |
| Tighter validation | Yes for existing callers sending old data |
