# Security test cases (run only against the local, isolated app)

All payloads below are standard, harmless probes. Use synthetic accounts and data; never run them against shared, staging or production systems (test-safely, dangerous operations).

| Area | Case | Expected |
| --- | --- | --- |
| AuthZ | User A reads `/orders/{id_of_B}` | 404 (or 403), no fields leaked |
| AuthZ | Tenant A lists with `tenant_id=B` | ignores the parameter or 403 |
| AuthZ | Regular user calls admin endpoint | 403 |
| AuthN | Expired / tampered / `alg: none` JWT | 401 |
| AuthN | Login with wrong password ×N | 429 after the limit, generic error text, Retry-After |
| Rate limit | `ds.py rate-limit-probe --url http://127.0.0.1:8000/api/login --requests 30 --expect-within 10` | pass |
| XSS | Save `<img src=x onerror=alert(1)>` as a name, view the page | text rendered, no script |
| SQLi | Search `' OR '1'='1` | normal empty result / 422, no SQL error |
| NoSQLi | Body `{"email": {"$ne": null}}` | 422 (type validation) |
| Traversal | `GET /files?name=../../etc/passwd`, `..%2f..%2fx`, absolute path | 400/404 |
| Upload | 2× size limit, wrong magic bytes with `.png`, zip with `../x` | 413 / 415 / rejected |
| SSRF | Fetch `http://127.0.0.1:9`, `http://169.254.169.254/` (mock server), redirect to internal | rejected before any request |
| Redirect | `?next=https://evil.example` | redirected to a safe default |
| CSRF | State-changing POST without token / from another origin | 403 |
| Mass assignment | `{"role": "admin", "price_minor": 1}` in update | fields ignored or 422 |
| Pagination | `limit=1000000` | capped at max |
| Body size | 10 MB JSON to a small endpoint | 413 |
| Errors | Force an exception | generic error + request id; no stack trace, SQL or secrets |
| Headers | GET a page | CSP, HSTS (https), nosniff, frame protection present |

## Example (pytest + FastAPI TestClient)

```python
def test_other_tenant_order_is_not_visible(client, tenant_a_token, order_of_tenant_b):
    response = client.get(f"/orders/{order_of_tenant_b.id}", headers={"Authorization": f"Bearer {tenant_a_token}"})
    assert response.status_code == 404
    assert str(order_of_tenant_b.id) not in response.text


def test_login_is_rate_limited(client):
    statuses = [client.post("/api/login", json={"email": "user@example.invalid", "password": "wrong"}).status_code
                for _ in range(12)]
    assert 429 in statuses
```
