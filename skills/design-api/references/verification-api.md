# API verification

| Need | Pass criterion |
| --- | --- |
| Contract diff before/after | `DS api-diff` finds every type/nullability/required change; breaking ones are intended and versioned |
| Real responses match the spec | responses from the running local app validate against the schema (Schemathesis or response validation in tests) |
| Frontend still works | consumer tests / typecheck of the frontend against regenerated types |
| PATCH semantics | missing field ≠ null |
| Pagination | walking all pages while rows are inserted returns no duplicates and loses none that existed at the start |
| Endpoint examples (API-011) | every affected method/path has invocation, inputs, success/error samples, permissions and data effects; examples match code/schema and verification status is explicit |

## 1. Export the spec and diff it

| Stack | Export (into the repo, e.g. `docs/openapi.json`) |
| --- | --- |
| Django + drf-spectacular | `python manage.py spectacular --format openapi-json --file docs/openapi.json` |
| Django + drf-yasg | `python manage.py generate_swagger docs/openapi.json` |
| Laravel (Scribe / l5-swagger) | `php artisan scribe:generate` / `php artisan l5-swagger:generate` |
| FastAPI | `python -c "import json, app.main as m; print(json.dumps(m.app.openapi()))" > docs/openapi.json` |

```bash
DS api-diff --spec docs/openapi.json --base-ref main --run <id>        # records api.contract_diff
DS api-diff --spec docs/openapi.json --base-file /tmp/openapi-before.json
```

Breaking findings fail the gate. An intended break needs a new version/endpoint or a documented transition, then `roster waive` with the reason — never edit the spec to hide it.

## 2. Validate real responses (Schemathesis, local only)

```bash
# App running on 127.0.0.1 with the test database; never a shared or production URL.
DS run-tests --profile integration_isolated --junit reports/st.xml -- \
  st run docs/openapi.json --url http://127.0.0.1:8000 --checks all --max-examples 50 --report junit --report-junit-path reports/st.xml
```

Use a test user token via `--env`; restrict to safe operations first (`--include-method GET`) and add unsafe ones only against a disposable DB. Without Schemathesis, validate responses in API tests with `jsonschema`/`openapi-core` against the exported spec.

## 3. Consumer side (frontend)

- Regenerate types from the spec (`openapi-typescript docs/openapi.json -o src/api/schema.d.ts`) and run `DS native-checks --kinds typecheck`: type errors are the consumer test.
- For hand-written clients, MSW handlers built from spec examples + component tests that exercise every field the screen reads.

## 4. PATCH and null

```python
def test_patch_missing_field_keeps_value(self):
    self.client.patch(url, {}, content_type="application/json")
    self.assertEqual(Order.objects.get(pk=self.order.pk).note, "keep")

def test_patch_null_clears_value(self):
    self.client.patch(url, {"note": None}, content_type="application/json")
    self.assertIsNone(Order.objects.get(pk=self.order.pk).note)
```

## 5. Pagination stability

```python
def test_cursor_pages_have_no_duplicates_or_gaps_under_inserts(self):
    make_orders(55)
    initial_ids = set(Order.objects.values_list("id", flat=True))
    seen, cursor = [], None
    while True:
        page = self.client.get("/api/orders", {"limit": 10, **({"cursor": cursor} if cursor else {})}).json()
        seen += [row["id"] for row in page["items"]]
        make_orders(1)  # concurrent insert between page requests
        cursor = page["next_cursor"]
        if not cursor:
            break
    self.assertEqual(len(seen), len(set(seen)))
    self.assertTrue(initial_ids <= set(seen))
```

## 6. Errors and limits

Each documented error status has a test (body shape included); oversized payloads and deep JSON are rejected; rate limit verified with `DS rate-limit-probe` on the local server (review-security).

## 7. Verify endpoint examples (API-011)

Run `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` with the optional contracts extra; the default roster requires `api.examples` for API/API-spec changes. Maintain the [structured manifest](automatic-examples.md) beside canonical docs. It checks all supplied operations, schema/curl/status/media/input coverage and local evidence claims; missing/invalid entries fail and unsupported validation blocks. To claim `locally-verified`, the API test writes a redacted observed exchange under the run and `DS run-tests --capture <path> --junit <report> --run <id> -- <test command>` fingerprints that fresh output. The checker requires matching capture content/hash, exact passing current-run testcase identity, a local isolated profile and fresh source state. Inspect that the linked test actually asserts the documented data effects; evidence linkage does not prove arbitrary business semantics or discover routes omitted from the export.

Use the coverage table and checklist in [endpoint-examples.md](endpoint-examples.md#verification-and-completion). Match examples against the actual route, schemas, validation, permission policy, service and error handler. Validate example values against the project's supported schema tools when available; schema-valid JSON alone does not prove authorization, side effects or runtime behavior. Link each required success/error scenario to its test, captured local response or explicit review evidence. Assert status, relevant headers and body, plus changed/preserved data and no side effects on denied/invalid requests. For 204/bodyless responses assert an empty body rather than inventing JSON.

Reproduce calls only on an isolated local app with synthetic fixtures through test-safely; never replay a destructive sample against dev/STG/production as a documentation check. Record command, fixture, revision, environment, result and evidence path for executed samples. Redact tokens/cookies and never publish credentials. Label unexecuted samples as illustrative and unavailable required checks as unverified/blocked. `api-diff` checks compatibility and `validate-skills` checks skill packaging; neither certifies endpoint example completeness or execution. Do not report API-011 satisfied while its coverage table has unexplained gaps.
