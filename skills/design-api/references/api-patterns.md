# API patterns (DRF first, Laravel second)

Match the neighbouring endpoints first (CTX-009): URL style, validation classes, permission decorators, error envelope, pagination shape.

## Request and response

- Separate input and output schemas (`OrderCreateSerializer` vs `OrderSerializer`; `StoreOrderRequest` vs `OrderResource`). Output never echoes internal fields (password hashes, internal flags, other tenants' ids).
- Explicit types: money as integer minor units + currency (or decimal string), timestamps ISO 8601 with offset, ids as strings if they can exceed 2^53 for JavaScript clients.
- Enums documented; clients must tolerate new values only if the contract says so.

## Validation and authorization (server side, always)

```python
class OrderViewSet(ProjectBaseViewSet):
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        # Tenant + ownership scoping in the query: an unknown id is 404, never someone else's row.
        return Order.objects.filter(tenant_id=self.request.tenant.id).select_related("customer")

    def get_object(self):
        order = super().get_object()
        self.check_object_permissions(self.request, order)  # owner/role rules per action
        return order
```

Laravel: `FormRequest::rules()` + `authorize()`, `Policy` per model (`$this->authorize('update', $order)`), route model binding scoped to the tenant (`->scopeBindings()` or a global scope).

List, export and download endpoints need the same scoping as detail endpoints — they are where BOLA leaks hide (review-security/authorization-matrix.md).

## PATCH: missing vs null

| Body | Meaning |
| --- | --- |
| `{}` | change nothing |
| `{"note": null}` | clear the note |
| `{"note": "x"}` | set it |

DRF: `partial=True` and check `"note" in serializer.validated_data` (not `.get("note") is None`). Laravel: `$request->has('note')` vs `$request->filled('note')`. TypeScript clients must not send `undefined` fields as `null`.

## Pagination

Cursor/keyset for feeds and large tables (`?cursor=…&limit=50`, response `{items, next_cursor}`), with a deterministic order including a unique tiebreaker (`created_at, id`). Page-number pagination only for small, admin-style lists. Cap `limit` server-side.

## Errors

One envelope for the whole API, using the project's existing one or Problem Details (RFC 9457):

```json
{"type": "https://errors.example.invalid/out-of-stock", "title": "Out of stock", "status": 409,
 "code": "out_of_stock", "errors": {"quantity": ["Only 2 left"]}, "correlation_id": "c-123"}
```

400/422 field errors map onto form fields; 401 vs 403 vs 404 chosen deliberately (404 for resources the caller may not know exist); 409 for conflicts/version mismatch; 429 with `Retry-After`. Never leak stack traces or SQL.

## Frontend compatibility

- Keep field names and casing the frontend already uses; if the API layer converts snake_case ↔ camelCase, keep that conversion in one place.
- Additive changes only within a version: new optional fields, new endpoints. Removing/renaming/retyping is a breaking change → new version or a transition period (`DS api-diff`).
- Generated clients/types (openapi-typescript, orval) are regenerated from the exported spec, never edited by hand.

## Idempotency and retries

POST that creates money/orders/messages accepts `Idempotency-Key`; the server stores key → result per tenant for a retention window and returns the same result on retry (implement-backend/backend-patterns.md).
