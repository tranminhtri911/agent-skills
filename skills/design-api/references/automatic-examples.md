# Automatic API-011 validation

`DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` checks **all HTTP method/path operations in the supplied OpenAPI document**. It reads files only: no app imports, curl execution, DNS, HTTP or database calls. The result ID is `api.examples`; API/API-spec changes require it in the default roster. A missing result blocks the report. The checker does not discover routes omitted from your exported contract: review the route/export scope separately.

## Installation and execution

The core runtime remains stdlib-only. This check additionally needs the optional `contracts` extra (`jsonschema`); missing support is `blocked`, never a pass. Use the environment's installing interpreter and the existing lockfile:

```bash
python3 -m pip install -e '.[contracts]' -c requirements-lock.txt
# Or install skills with an optional venv and explicitly selected extras:
python3 agent-skills.py install --with-venv --extras contracts
```

Do not change the project's API/framework version to satisfy the checker. JSON OpenAPI 3.0/3.1 is supported; YAML also needs PyYAML already installed. Export JSON when YAML support is unavailable. No dependency is downloaded by `api-examples` itself.

```bash
DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>
DS trace --run <id> --file acceptance.json
DS report --run <id> --summary-file summary.md
```

Default check ID: `api.examples`. Repeated checks for separate service contracts must use distinct `--check-id` values registered with `DS roster add`; do not overwrite the first service's evidence with another service's result. The result declares its spec/file scope and can be linked from acceptance criteria as documentation/schema evidence, never as proof of all backend business semantics.

## Manifest format version 1

Use [the complete fictional manifest](../assets/api-examples.json) and [its OpenAPI fixture](../assets/openapi-example.json) as syntax examples, then replace their fictional contract with the project's actual exported API and evidence. Keep the manifest beside canonical API docs; it is a machine-readable coverage index, not another source of business rules. The existing [human-readable endpoint template](endpoint-examples.md) still explains information that a structural checker cannot infer.

Top-level fields are `format_version: 1`, a literal loopback `base_url`, and `endpoints`. There must be exactly one endpoint entry for each method/path in the supplied spec; unknown, duplicate and missing entries fail. Empty contracts/manifests cannot pass. Additional manifest properties fail to catch misspellings.

| Endpoint field | Required content / check |
| --- | --- |
| `method`, `path` | Exact method and templated path from OpenAPI, including version prefix where present |
| `documentation` | Repository-relative canonical documentation file, optionally with an existing Markdown heading anchor |
| `sources` | Nonempty list of existing repository-relative source/policy references; human review must confirm relevance |
| `purpose`, `permissions` | Endpoint purpose and actual role/scope/tenant/owner policy; nonempty explanation |
| `security` | Exact effective OpenAPI Security Requirement array, including root inheritance or explicit public `[]` |
| `inputs` | Entries for every parameter and request body field/container/array item; see keys below |
| `effects` | Nonempty `changes`, `preserves`, `failure`, `external`, `transaction`, `retry` descriptions; explain no-effect/N/A cases |
| `applicability` | Each category below has `{"cases":["case-id"]}` or `{"reason":"justification"}` |
| `cases` | Concrete invocation, request/response and evidence for every declared response status/media type and applicable failure category |

Input keys are `path:name`, `query:name`, `header:Name` and `body:<media-type>:<JSON-pointer>`. The whole body uses an empty pointer, e.g. `body:application/json:`. Nested properties use escaped JSON pointers (`/customer/name`), array items use `/*`. Containers also need documentation. Request read-only fields are excluded and cannot appear in successful request examples.

Each input entry contains `description`, `omitted`, `constraints` and a typed synthetic `example`. These examples are checked against the exported schemas; types/requiredness/nullability come from the contract, while explanatory text still requires review. Multiple request media types need separate body keys and representative samples.

Applicability categories: `validation`, `unauthenticated`, `forbidden`, `not_found`, `conflict`, `rate_limit`. All must be present. Case IDs must exist and use compatible response statuses. Declared 400/422, 403, 404, 409 and 429 responses cannot be hidden behind the corresponding N/A reason. Required authentication also needs a rejection example. Every declared response, including explicit 5xx, status ranges and `default`, needs a concrete representative case; the checker does not invent undocumented errors.

## Case fields and comparisons

| Field | Required content |
| --- | --- |
| `id`, `trigger` | Unique ID within the endpoint and clear fixture/condition producing this scenario |
| `curl` | One literal curl with explicit `--request`/`-X`, loopback URL, literal headers and embedded synthetic JSON; no shell/config/file indirection |
| `request.path`, `.query`, `.headers` | Typed path/query values and literal header strings; use empty objects when absent |
| `request.body` | JSON value, including explicit JSON null when valid; **omit the key** for no body |
| `request.body_raw` | Alternative malformed JSON string for a parser rejection; never declare both body forms |
| `request_valid` | Whether the request satisfies the exported parameter/body schemas; must be true on success. A business validation error may still have a schema-valid request |
| `response.status`, `.headers`, `.body` | Concrete HTTP status and headers plus JSON body; bodyless responses omit the body key (JSON null is a body) |
| `assertions` | Nonempty list describing changed/preserved data and relevant side-effect assertions for this scenario |
| `verification` | One of the evidence forms below; unsupported/unsubstantiated execution claims fail |

The parser compares curl method, URL/path fixtures, decoded query values, headers and body to the structured request. Supported curl options: `--request`/`-X`, `--url` or one URL, `--header`/`-H`, `--data-raw`/`--data`/`-d`, optional `--max-time` up to 60 seconds and basic output flags (`--silent`, `--show-error`, `-s`, `-S`, `-sS`, `-i`, `--include`). It rejects other options rather than interpreting shell substitutions or reading `@file`/curl config. Use explicit synthetic header placeholders, not credentials.

Success requests and all response bodies must match their schemas. Intentionally invalid requests must actually violate a schema/parser/required-parameter rule. A rejected permission/business case can instead use `request_valid: true`. Headers are case-insensitive; duplicates/line breaks are rejected. Success samples include required auth headers/query keys, not an inferred permission grant. Declared response headers need examples; 429 includes `Retry-After`. HEAD and 204/304/bodyless responses cannot fabricate a JSON body. `false` body versus omitted body is checked distinctly.

## Execution evidence

Unexecuted examples:

```json
{"status": "illustrative"}
```

or `{"status":"schema-validated"}`. A successful checker run establishes static schema/coverage checks on the supplied files. It does not make either form a runtime test.

A locally verified case uses:

```json
{
  "status": "locally-verified",
  "test": "tests/test_widgets.py::Widgets::test_create",
  "check": "tests.integration",
  "capture": ".devskills/runs/<current-id>/artifacts/widget-created.json"
}
```

The current run must already contain a completed, passing, fresh check produced under `unit_offline` or `integration_isolated`, with an exact matching non-skipped testcase in its JUnit identities. A passing linter or aggregate count is insufficient. The capture is a redacted JSON exchange written during that execution, inside the same run:

Run that test with `DS run-tests --capture <repo-relative-run-artifact.json> --junit <report> --run <id> -- <test command>`. The runner hashes the fresh capture after completion, stores it under `details.captures`, and blocks missing/stale/linked/oversized captures even when the test command exits zero. The example checker requires the stored hash to match; manually creating or editing a capture after the recorded execution is insufficient.

```json
{
  "case_id": "created",
  "test": "tests/test_widgets.py::Widgets::test_create",
  "method": "POST",
  "path": "/widgets",
  "request": {"path": {}, "query": {}, "headers": {"Content-Type": "application/json"}, "body": {"name": "Demo widget", "note": null}},
  "response": {"status": 201, "headers": {"Content-Type": "application/json", "Location": "/widgets/42"}, "body": {"id": 42, "name": "Demo widget", "note": null}}
}
```

The capture must exactly match the case request/response, method/path, case ID and test reference. Its file timestamp must fall within the linked execution window; a new/manual capture after the check is rejected. Prepare the manifest and fixture sources before running tests so subsequent source edits correctly invalidate stale evidence. Have the API test capture actual handler responses and assert data effects; do not serialize an expected fixture and call it an observed response. Existing local reports/captures remain editable evidence, not independent attestations. The tool cannot infer whether a test actually asserts the business meaning of every `assertions` string; reviewers must inspect that test. `linked_local_evidence` in results reports the linkage checked, not a claim of production execution.

## Unsupported cases and gates

- **Fail (exit 3):** missing/duplicate endpoint/case/input/response coverage, invalid example values, incorrect curl, false N/A declarations or unsupported execution claims/evidence.
- **Blocked (exit 4):** missing optional schema support, unsupported OpenAPI versions/schema keywords/formats, external/unresolved/recursive references or non-JSON media/parameter encodings needing an adapter. These require a supported export/adapter or explicit reviewed applicability handling; never silently mark them covered.
- **Usage error (exit 2):** malformed JSON, duplicate JSON keys, invalid/unsafe file paths, unavailable/oversized inputs or invalid base URL. Neither a failure nor a usage error counts as completed validation.
- Only local references are resolved. Input files are limited to 2 MiB, schema depth to 32, and manifest sizes to 1,000 endpoints/200 cases per endpoint. JSON Schema validation uses the installed optional `jsonschema` version; unsupported features block. No remote schema retrieval is permitted.

Schema expansion is capped at 10,000 nodes per value validation. Regex assertions use a conservative bounded profile: patterns over 256 characters, groups/alternation/backreferences or multiple unbounded quantifiers block for a reviewed adapter rather than risking unbounded regex evaluation. Strict JSON/YAML rejects duplicate keys so an operation cannot disappear through last-value parsing. This profile is deliberately narrower than full OpenAPI/JSON Schema support.

OpenAPI 3.0 nullable and boolean exclusive bounds are translated to JSON Schema; 3.1 uses native null types/numeric bounds. Read-only request and write-only response fields are rejected. Schemas with unresolved semantics do not collapse into `{}`. Security requirement arrays are copied from the actual root/operation contract; narratives cannot override them.

Primary references used for implementation: [OpenAPI 3.0.3](https://spec.openapis.org/oas/v3.0.3.html), [jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/). They explain schema/security semantics, not the correctness of a target application's policy.

## Bundled fictional contract

The two asset files define a public `POST /widgets` with a name/note body, a 201 JSON success and a 422 JSON validation failure. They are **fictional, illustrative and not executed**. The effects/default descriptions are proposed fixture semantics, not behavior established by an app or schema. Source/documentation references point here because no application implementation exists. The validator can confirm this fixture's static completeness/schema consistency; it cannot establish a running endpoint or validate the proposed business semantics.

From this repository, run the static fixture check:

```bash
python3 skills/design-api/scripts/ds.py api-examples --repo skills/design-api \
  --spec assets/openapi-example.json --file assets/api-examples.json
```

There is deliberately no curl/API execution in this example. In real work, replace fictional sources, schemas, roles, defaults, effects and failure applicability with inspected project evidence before treating the manifest as endpoint documentation.
