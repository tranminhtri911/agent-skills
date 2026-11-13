# Backend patterns (Django/DRF first, Laravel second)

Start from the repo: the reference module and project bases found by discover-codebase (CTX-009) override every example below. The examples show *where responsibilities go*, not a new architecture to introduce.

## Responsibilities

| Layer | Owns | Never |
| --- | --- | --- |
| View / controller | parse + validate input, authn/authz, call one use case, map result/errors to HTTP | business rules, queries, transactions spanning several calls |
| Service / use case | business rules, transaction boundary, ordering of side effects | HTTP objects (`request`, `Response`), template rendering |
| Repository / ORM query layer | queries, locking, tenant scoping | business decisions |
| Job / command | batching, checkpoints, retries; calls the same use case as the API | a second copy of the rule |

The same rule must run on **every path that writes the data**: API, admin, worker, import, management command. Put it in the use case, not in a serializer or a form only one path uses.

## Django / DRF

```python
# orders/services.py
from django.db import transaction
from django.db.models import F

class OutOfStock(DomainError):  # Project's own error base (see core/errors)
    code = "out_of_stock"

def place_order(*, tenant_id: int, user_id: int, sku: str, quantity: int, idempotency_key: str) -> Order:
    """Create one order per idempotency key; reserves stock atomically.

    Input: validated values (no request object). Output: the order (existing one on retry).
    Errors: OutOfStock. Side effects: order email is queued only after commit.
    """
    existing = Order.objects.filter(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            # Conditional UPDATE: no read-modify-write window, no lost update.
            updated = (Product.objects.filter(tenant_id=tenant_id, sku=sku, stock__gte=quantity)
                       .update(stock=F("stock") - quantity))
            if updated == 0:
                raise OutOfStock()
            order = Order.objects.create(tenant_id=tenant_id, user_id=user_id, sku=sku, quantity=quantity,
                                         idempotency_key=idempotency_key)
            transaction.on_commit(lambda: send_order_email.delay(order.id))
    except IntegrityError:
        # Unique (tenant_id, idempotency_key): a concurrent retry won. The whole block rolled back
        # (stock restored); query only after leaving it — an aborted transaction rejects new queries.
        return Order.objects.get(tenant_id=tenant_id, idempotency_key=idempotency_key)
    return order
```

```python
# orders/views.py — thin; follows the project's decorators/permission classes
class OrderCreateView(ProjectBaseAPIView):
    permission_classes = [IsAuthenticated, IsTenantMember]

    def post(self, request):
        payload = OrderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order = place_order(tenant_id=request.tenant.id, user_id=request.user.id,
                            idempotency_key=request.headers["Idempotency-Key"], **payload.validated_data)
        return Response(OrderSerializer(order).data, status=201)
```

Notes:
- `transaction.atomic()` around the whole multi-step write; nested `atomic` creates savepoints. Never call payment/email/HTTP inside it: use `on_commit` or an outbox row (design-reliability).
- `select_for_update()` only inside `atomic`, on the fewest rows, in a consistent order (by id) to avoid deadlocks; prefer conditional `UPDATE … WHERE` or `F()` when one statement can express the rule.
- `ATOMIC_REQUESTS=True` makes every view one transaction: keep views short and still move side effects to `on_commit`.
- Querysets are lazy: evaluate inside the transaction when the result decides a write.
- Celery tasks receive ids, not model instances; re-read and re-check state inside the task (it may run twice).

## Laravel

```php
// app/Services/OrderService.php
public function place(int $tenantId, int $userId, string $sku, int $qty, string $key): Order
{
    if ($existing = Order::where('tenant_id', $tenantId)->where('idempotency_key', $key)->first()) {
        return $existing;
    }
    return DB::transaction(function () use ($tenantId, $userId, $sku, $qty, $key) {
        $updated = Product::where('tenant_id', $tenantId)->where('sku', $sku)->where('stock', '>=', $qty)
            ->decrement('stock', $qty);
        if ($updated === 0) {
            throw new OutOfStockException();
        }
        $order = Order::create([...]);
        DB::afterCommit(fn () => SendOrderMail::dispatch($order->id));
        return $order;
    }, attempts: 3); // Retries on deadlock only.
}
```

- Controller: `FormRequest` for validation, `Policy`/`Gate` for authorization, `JsonResource` for output, service for the rule.
- `lockForUpdate()` inside `DB::transaction`; jobs implement `ShouldBeUnique` or check an idempotency key; `$afterCommit = true` on jobs dispatched inside transactions.

## Errors and resources

- One domain error base per project; the boundary maps it to the API error envelope. Unexpected errors: log with correlation id, return a generic 500, never the stack trace.
- Every external call: timeout, bounded retries with backoff only for idempotent operations, and a circuit/fallback decision (design-reliability).
- Files, HTTP clients, cursors: context managers / `finally`; no module-level connections created at import time.
