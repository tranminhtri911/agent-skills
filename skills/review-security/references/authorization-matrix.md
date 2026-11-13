# Authorization matrix (BOLA / IDOR)

Broken object-level authorization (OWASP API1) is the most common API flaw: the endpoint checks *that* you are logged in, not *whose* object you touch. Prove it with a matrix, not with one happy-path test.

| Need | Pass criterion |
| --- | --- |
| User A vs user B | A cannot read, change, delete, export or download B's data (same tenant, other owner) |
| Tenant isolation | nothing from tenant X is reachable from tenant Y, by id, list, search, export or file URL |
| Denied request has no side effect | after a 403/404: no row changed, no job/email/webhook queued, no file written |
| Roles | each role gets exactly the actions the spec grants |

## Build the matrix

Rows = endpoint × action (including **list, search, export, download, bulk, nested routes, GraphQL fields, websocket channels**). Columns = actor: anonymous, same-tenant owner, same-tenant other user, same-tenant admin, other-tenant user, other-tenant admin, deactivated user.

| Endpoint / action | anon | owner | other user | tenant admin | other tenant | expected for "no" |
| --- | --- | --- | --- | --- | --- | --- |
| GET /orders (list) | 401 | own only | own only | all in tenant | own tenant only | filtered, not 403 |
| GET /orders/{id} | 401 | 200 | 404 | 200 | 404 | 404 (do not confirm existence) |
| PATCH /orders/{id} | 401 | 200 | 404 | 200 | 404 | 404 |
| GET /orders/export.csv | 401 | own rows | own rows | tenant rows | own tenant | filtered |
| GET /files/{key} | 401 | 200 | 404 | 200 | 404 | signed URL scoped and short-lived |

Write it in the decision memo or the test file header; every "no" cell is a test.

## Parametrized tests (Django example)

```python
CASES = [
    # (actor, method, url_name, expected_status)
    ("other_user", "get", "order-detail", 404),
    ("other_user", "patch", "order-detail", 404),
    ("other_tenant_admin", "get", "order-detail", 404),
    ("other_tenant_admin", "get", "order-export", 200),  # but must not contain the victim's rows
    ("anonymous", "get", "order-list", 401),
]

@parameterized.expand(CASES)
def test_access(self, actor, method, url_name, expected):
    before = snapshot_state()  # rows, outbox, queued jobs, files
    client = self.client_for(actor)
    response = getattr(client, method)(reverse(url_name, kwargs=self.kwargs_for(url_name)), {"note": "x"},
                                       content_type="application/json")
    self.assertEqual(response.status_code, expected)
    if expected >= 400:
        self.assertEqual(snapshot_state(), before, "a denied request must not change anything")
    if url_name.endswith(("list", "export")):
        self.assertNotIn(self.victim_order_id, ids_in(response))
```

`snapshot_state()` = counts/hashes of the touched tables, the outbox, `mail.outbox`, queued Celery/Laravel jobs (`Queue::fake()`), storage listing.

Laravel: Pest/PHPUnit datasets with `actingAs($user)`; `Queue::fake()`, `Mail::fake()`, `Storage::fake()` to assert no side effects on denial.

## Where checks must live

- Scope queries by tenant and owner in the repository/queryset (`get_queryset`, global scopes), so list/export/search inherit it.
- Object checks after loading, before any side effect: validate → load scoped → authorize → act.
- Ids from the client (body, query, headers, nested routes `/tenants/{t}/orders/{o}`) are untrusted: verify that `o` belongs to `t` and `t` to the caller.
- Background jobs re-check permission/tenant with ids from the job payload; a job created by an admin action must not run with broader rights than intended.
- File downloads: authorize on every request or use short-lived signed URLs bound to the object.
