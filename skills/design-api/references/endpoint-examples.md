# Endpoint documentation and examples (API-011)

Use this reference for every new or changed HTTP **method + path**. Keep the completed content in the project's existing API docs, OpenAPI descriptions/examples or established equivalent. Do not introduce another documentation system. Updating an existing endpoint also documents preserved behavior and intended differences; examples must not silently redefine its contract.

## Required coverage

Identify the affected endpoints from the actual routes/controllers and consumers, not just the endpoint mentioned in the task. For each one, complete the template below and link its scenarios to evidence. Shared authentication/error documentation may be referenced, but each endpoint still identifies its required role/scopes and applicable success/failure cases.

| Method + path | Source/schema/policy | Documentation + sample location | Required scenarios | Test/review evidence | Sample verification status / gap |
| --- | --- | --- | --- | --- | --- |
| `<METHOD /path>` | `<actual paths/symbols>` | `<canonical document/anchor>` | `<success + applicable failures>` | `<exact test/report or review location>` | `<status and missing checks>` |

Every section needs concrete content or **N/A with a reason**. A generic schema, one API-wide JSON example, a screenshot of Swagger or an unreviewed generated document does not replace endpoint-specific examples. Do not invent unsupported response codes, fields or permissions to fill the template.

## Reusable endpoint template

### 1. Purpose, contract and permission

- **Method + path / operation ID:** exact routing, including any prefix/version.
- **Purpose:** what the caller accomplishes; state synchronous versus asynchronous completion.
- **Contract sources:** actual route/controller, request/response schemas, validator, authorization policy, service and error handler; include the reviewed commit/snapshot.
- **Change:** new endpoint, changed behavior, preserved behavior and compatibility/deprecation notes.
- **Caller:** authentication scheme; required role, permission or scope; tenant/owner boundaries; public endpoints explicitly state that authentication is not required. Reuse the project's existing policies.
- **Preconditions:** synthetic fixture IDs, initial state/version, feature flags and other setup needed to reach the demonstrated result.
- **Limits:** body/file size, pagination, rate/concurrency limit and timeouts where applicable; use the implemented configuration and units.

### 2. Request fields

| Location | Field | Type / format | Required? | Nullable? | Default / effect when omitted | Constraints / allowed values | Synthetic example |
| --- | --- | --- | --- | --- | --- | --- | --- |
| path/query/header/body | `<name>` | `<type, units/encoding>` | yes/no/conditional + condition | yes/no | `<actual behavior>` | `<range, length, enum, cross-field rule>` | `<value>` |

Include nested fields and relevant request headers. Explain omitted/null/empty/zero behavior when different, especially PATCH. Document unknown-field handling, arrays, date/time zone and monetary precision where applicable. For a request without a body, explicitly say **Request body: none**; do not add `{}` unless the endpoint expects it.

### 3. Invocation sample

Provide a complete `curl` showing method, local URL, encoded path/query values, auth/required headers and body. Include content type, accept type, idempotency/version headers, multipart parts or cookie/CSRF setup when the actual API needs them. For public APIs, show the applicable request without a fabricated auth header.

Use a loopback base URL for executable examples, synthetic IDs and placeholder credentials. Explain every placeholder and the fixture/environment needed to replace it. A credential placeholder is not a real token, and a sample command is not authorization to execute it. No production host, real token, customer record or real payment in examples.

### 4. Success response

- Exact HTTP status and relevant headers (`Content-Type`, `Location`, `ETag`, request ID, pagination links, etc., only when emitted).
- A concrete body matching the response schema, plus field meanings/types/units when the schema does not explain them. Cover distinct success shapes, empty collections and page boundaries where relevant.
- **204 / other bodyless response:** explicitly state **Response body: empty (zero bytes)**. Do not attach a JSON envelope.
- **202 / asynchronous response:** show the operation ID, status location/endpoint, polling rules, terminal success/failure response and when effects become visible.
- Binary/file/stream responses: show media type, meaningful headers, representation and completion/error behavior rather than inventing a JSON body.

### 5. Failure scenarios

For **each applicable documented failure**, show the triggering request/variation, exact status, relevant headers, concrete response body/stable code and expected data/effects. A shared base request plus explicit field/header changes is sufficient when it unambiguously reproduces the case.

| Scenario | Trigger/request variation | Status | Headers + sample body | Data/effect assertion | Evidence |
| --- | --- | --- | --- | --- | --- |
| Malformed input / unsupported media | `<actual parser/media failure>` | `<implemented status>` | `<headers + concrete body>` | `<expected state>` | `<test/review>` |
| Validation | `<missing/invalid/boundary field>` | `<implemented status>` | `<field errors + stable code>` | `<expected state>` | `<test/review>` |
| Unauthenticated | `<absent/invalid/expired credentials>` | `<implemented status>` | `<auth challenge if emitted + body>` | no protected data or mutation | `<test/review>` |
| Forbidden / wrong tenant or owner | `<authenticated actor lacking access>` | `<implemented 403/404 policy>` | `<body without hidden resource details>` | no mutation, job, email or file effect | `<test/review>` |
| Missing resource | `<nonexistent synthetic ID>` | `<implemented status>` | `<body>` | `<expected state>` | `<test/review>` |
| Conflict / duplicate / stale version | `<state/version/key conflict>` | `<implemented status>` | `<body + retry/recovery instruction>` | no duplicate or partial effect | `<test/review>` |
| Limits / dependency / other failure | `<actual size/rate/timeout/domain condition>` | `<implemented status>` | `<Retry-After or other headers if emitted + body>` | `<rollback, pending state or other actual policy>` | `<test/review>` |

These are coverage prompts, not a mandate to return every listed status. Mark inapplicable scenarios with a reason. Preserve existing error conventions and the deliberate 403/404 resource-disclosure policy. Include safely represented server/dependency errors when the endpoint documents them; never expose stack traces, SQL, credentials or raw provider internals.

### 6. Business and data effects

| Target / effect | Initial state | State after success | State after denial/validation failure | Rule/source |
| --- | --- | --- | --- | --- |
| `<target record>` | `<synthetic state>` | `<changed fields/deletion/soft deletion>` | `<unchanged>` | `<source>` |
| `<related/master/shared data>` | `<IDs + relevant contents>` | `<explicitly changed or preserved>` | `<unchanged>` | `<source>` |
| `<job/email/event/file/provider call>` | `<initial state>` | `<actual effect and timing>` | none | `<source>` |

Explain transaction boundaries, partial-failure behavior and visibility timing. For delete operations, identify records/links removed versus master/shared/history records retained; a relationship alone does not establish deletion scope. Describe replay/idempotency behavior and what a caller should do after a timeout with an unknown outcome. Do not claim one transaction covers independent DBs/services without evidence.

### 7. Sample verification status

Choose the strongest status actually supported **per sample/scenario**:

| Sample status | Required support | Does not establish |
| --- | --- | --- |
| **Illustrative — not executed** | synthetic example, reviewed against identified source/contract; record assumptions/unknowns | a real request ran or runtime behavior passed |
| **Schema-validated only** | validator/test command, schema revision and result for the sample values | authorization, business effects or runtime completion |
| **Locally verified** | captured execution against an isolated local app/API test with synthetic fixtures; revision, command/test, environment, status/headers/body and effect assertions recorded | dev/STG/production behavior or untested cases |

These labels describe examples; they do not replace `trace`'s evidence statuses. Do not promote a proposed schema to an implemented API, a mocked response to an executed handler, or local results to deployed evidence. Keep credentials redacted and record missing required checks as unverified/blocked.

## Worked example — fictional, not executed

**Every route, field, permission, fixture, timestamp, status and response in this section is illustrative. No such endpoint or execution is asserted to exist in this repository.** This demonstrates the format; replace the fictional contract with evidence from the target project. Middleware-specific size/rate/server failures still need their own samples when applicable to the real endpoint.

### Purpose and preconditions

- `PATCH /api/admin/products/{product_id}` updates a product's name/note in the caller's tenant. Authentication: bearer token; permission in this fictional contract: tenant admin. Cross-tenant/missing products return 404.
- Fixture: product 42 in the test admin's tenant starts as `name="Old demo name"`, `note="Demo note"`, `version=7`. Category 3, unit 2 and other products already exist and must remain unchanged.
- Atomic update of name/note/version/updated timestamp in one local DB transaction. A stale version returns 409 without writes. No email, queue, payment or file effect is part of this fictional operation.
- Source/schema/policy references: **N/A — fictional illustration**. Sample status: **Illustrative — not executed**. No local server or token is supplied.

### Request

| Location | Field | Type | Required? | Nullable? | Omitted behavior | Constraints | Example |
| --- | --- | --- | --- | --- | --- | --- | --- |
| path | `product_id` | integer | yes | no | route cannot match | positive integer, visible in caller's tenant | `42` |
| header | `Authorization` | bearer credential | yes | no | 401 | synthetic admin token for the fixture tenant | `Bearer <TEST_TOKEN>` |
| header | `Content-Type` | media type | yes for this body | no | parser policy must be documented in real API | `application/json` | `application/json` |
| body | `version` | integer | yes | no | 422 | integer >= 1; must equal stored version | `7` |
| body | `name` | string | at least one of name/note | no | retain old name | 1–120 characters; whitespace-only rejected | `Demo product` |
| body | `note` | string | at least one of name/note | yes | retain old note | up to 500 characters; null clears; empty string stays empty | `null` |

Unknown body fields are rejected with 422 in this fictional contract. The example does not accept tenant/owner/role or category/unit changes from the body.

```bash
# Illustration only. Requires an isolated local app, the fixture above and a
# scoped synthetic credential substituted for <TEST_TOKEN> before any execution.
curl --max-time 10 --request PATCH \
  'http://127.0.0.1:8000/api/admin/products/42' \
  --header 'Authorization: Bearer <TEST_TOKEN>' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, application/problem+json' \
  --data-raw '{"version":7,"name":"Demo product","note":null}'
```

### Success sample

Status: `200 OK`. Header: `Content-Type: application/json`. In this illustration all displayed fields are required; `note` may be null; `updated_at` is a UTC ISO-8601 timestamp.

```json
{
  "id": 42,
  "name": "Demo product",
  "note": null,
  "version": 8,
  "updated_at": "2026-11-06T00:00:00Z"
}
```

The timestamp is invented synthetic data, not a captured server time. Success changes only this product's name, note, version and updated timestamp. Category 3, unit 2 and other products retain their IDs and contents. Authentication/authorization/validation/version failures leave all those records unchanged and enqueue/send nothing.

### Failure samples

Start from the base request above and reset the fixture before each independent scenario. All rows below are **illustrative — not executed**. Bodies use `Content-Type: application/problem+json`; 401 additionally emits `WWW-Authenticate: Bearer` in this fictional contract.

| Scenario | Change to base request | Status | Concrete sample body |
| --- | --- | --- | --- |
| Unauthenticated | remove Authorization header | 401 | `{"type":"about:blank","title":"Unauthorized","status":401,"code":"AUTH_REQUIRED","detail":"Authentication is required."}` |
| Forbidden | use a synthetic non-admin token from the same tenant | 403 | `{"type":"about:blank","title":"Forbidden","status":403,"code":"ACCESS_DENIED","detail":"This action is not permitted."}` |
| Missing or cross-tenant product | path ID `999999`, absent from fixtures, or token for an admin of another tenant | 404 | `{"type":"about:blank","title":"Not found","status":404,"code":"NOT_FOUND","detail":"Product not found."}` |
| Invalid name | replace body with `{"version":7,"name":""}` | 422 | `{"type":"about:blank","title":"Validation failed","status":422,"code":"VALIDATION_ERROR","detail":"Request validation failed.","errors":{"name":["Use 1 to 120 characters."]}}` |
| Stale version | replace body version with `6` | 409 | `{"type":"about:blank","title":"Conflict","status":409,"code":"VERSION_CONFLICT","detail":"Reload the product before updating."}` |

Each denied/invalid/conflicting row asserts no data change and no external effect, not just the HTTP status. The table illustrates application failures; it is not a complete middleware contract to copy into another app. Add the actual parser/media/size/rate/dependency error cases from the target project's implementation and explain any inapplicable cases.

### Replay and evidence

- After success, sending the original version-7 request again returns 409 in this fictional contract. Read the current product and reconcile after an unknown timeout; do not blindly retry or promise duplicate-request replay.
- A request containing only `version` fails validation because neither editable field was provided. An omitted name/note retains its old value; `name=null` fails; `note=null` clears it. These need their own samples/tests when documenting this behavior in a real endpoint.
- Local verification evidence: **none**. JSON/shell syntax checking of this reference alone does not change that status.

## Verification and completion

1. Review every coverage row against route/controller, schema, validation, policy, service/error handler and relevant consumers at the identified revision. Confirm actual fields, defaults, permissions, statuses, headers and data effects; reconcile spec/code differences without changing behavior outside the task.
2. Parse JSON/shell samples and validate payloads against supported schema tooling when available. Then use isolated local API tests/captures for required runtime scenarios: assert status/headers/body, authorized changes, preserved data and no side effects for denied/invalid calls. Exercise boundary values and conditional success/failure shapes, not just one happy path.
3. For executed scenarios, record exact command/test, revision, environment, synthetic fixture, result and evidence path. Use test-safely for execution. Never run the documented mutation just to make documentation appear verified, and never point documentation checks at shared/production resources.
4. Update the canonical docs/OpenAPI examples, this endpoint's coverage row and affected consumers in the same change. If the project has a knowledge index, rebuild/check it after document changes. Review generated examples rather than assuming generators chose realistic values.
5. Hand over links to endpoint docs and evidence with remaining gaps. Missing required sections or scenarios leave API-011 incomplete; unexecuted required tests remain unverified/blocked. Explicitly justified N/A cases are acceptable. Full documentation can contain illustrative examples if clearly labeled, but that does not satisfy a separate requirement for executed API evidence.

**Automatic enforcement:** Run `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` with the [structured manifest](automatic-examples.md). `api.examples` is required by the default roster for API/API-spec changes. It checks all supplied OpenAPI operations for sample/schema/curl/status/media/input coverage and justified N/A cases. Missing/invalid entries fail; unsupported validation blocks. It never executes requests. A `locally-verified` claim needs exact passing current-run test identity, a fresh isolated check and a matching exchange captured/fingerprinted by `run-tests --capture`.

**Review boundary:** Verify route/export scope, policy and data effects separately: the checker cannot discover omitted app routes or prove business semantics from documentation. `validate-skills` checks packaging and `api-diff` checks compatibility; neither replaces `api.examples` or semantic review. Static validation never turns illustrative examples into runtime evidence.
