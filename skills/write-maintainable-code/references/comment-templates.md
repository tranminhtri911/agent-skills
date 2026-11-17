# Comment and doc templates per language

Rule of thumb: doc comments describe the **contract** (purpose, inputs and constraints, output, errors, side effects); inline comments explain **why**. The templates below are examples: follow the repository's existing comment style (block or line comments), unless `.devskills.toml` `[code].multiline_comment_style` sets one (DOC-003).

## TypeScript / JavaScript (TSDoc/JSDoc)

```typescript
/**
 * Reserve stock for every line of an order inside the caller's transaction.
 *
 * @param orderId - Order being reserved; must belong to `tenantId`.
 * @param lines - Positive quantities per SKU; duplicates are merged by the caller.
 * @returns Reservation ids in line order.
 * @throws OutOfStockError when any SKU lacks available quantity (nothing is reserved).
 */
export async function reserveStock(orderId: string, lines: OrderLine[], tenantId: string): Promise<string[]> {
  /*
   * Conditional UPDATE instead of read-then-write: two buyers racing for the last
   * item cannot both succeed, and no row lock is held while computing totals.
   */
  ...
}
```

## Python (comments `#`, docs = docstrings)

```python
def reserve_stock(order_id: str, lines: list[OrderLine], tenant_id: str) -> list[str]:
    """Reserve stock for every order line inside the caller's transaction.

    Args:
        order_id: Order being reserved; must belong to tenant_id.
        lines: Positive quantities per SKU.
        tenant_id: Tenant that owns the order and the inventory rows.

    Returns:
        Reservation ids in line order.

    Raises:
        OutOfStockError: Any SKU lacks quantity; nothing is reserved.
    """
    # Conditional UPDATE instead of read-then-write: concurrent buyers cannot
    # both take the last item, and no lock is held while computing totals.
    ...
```

## Java (Javadoc)

```java
/**
 * Reserves stock for every order line inside the caller's transaction.
 *
 * @param orderId order being reserved; must belong to {@code tenantId}
 * @param lines   positive quantities per SKU
 * @return reservation ids in line order
 * @throws OutOfStockException when any SKU lacks quantity (nothing is reserved)
 */
public List<String> reserveStock(String orderId, List<OrderLine> lines, String tenantId) {
    /* Conditional UPDATE avoids the read-check-write race for the last item. */
    ...
}
```

## C# (XML documentation)

```csharp
/// <summary>Reserves stock for every order line inside the caller's transaction.</summary>
/// <param name="orderId">Order being reserved; must belong to <paramref name="tenantId"/>.</param>
/// <param name="lines">Positive quantities per SKU.</param>
/// <returns>Reservation ids in line order.</returns>
/// <exception cref="OutOfStockException">Any SKU lacks quantity; nothing is reserved.</exception>
public Task<IReadOnlyList<string>> ReserveStockAsync(string orderId, IReadOnlyList<OrderLine> lines, string tenantId)
{
    /* Conditional UPDATE avoids the read-check-write race for the last item. */
    ...
}
```

## PHP (PHPDoc)

```php
/**
 * Reserve stock for every order line inside the caller's transaction.
 *
 * @param string      $orderId  Order being reserved; must belong to $tenantId.
 * @param OrderLine[] $lines    Positive quantities per SKU.
 * @return string[]             Reservation ids in line order.
 * @throws OutOfStockException  When any SKU lacks quantity (nothing is reserved).
 */
public function reserveStock(string $orderId, array $lines, string $tenantId): array
{
    /* Conditional UPDATE avoids the read-check-write race for the last item. */
}
```

## Go (convention: `//` everywhere, doc comment starts with the name)

```go
// ReserveStock reserves stock for every order line inside the caller's transaction.
// It returns ErrOutOfStock when any SKU lacks quantity; nothing is reserved then.
func ReserveStock(ctx context.Context, tx pgx.Tx, orderID string, lines []OrderLine) ([]string, error) {
```

## SQL (migrations)

```sql
/*
 * Why: checkout lists a tenant's open orders newest first (query in orders/repository.py).
 * Verified with EXPLAIN on synthetic data (2M rows); write cost acceptable for ~50 inserts/s.
 */
CREATE INDEX CONCURRENTLY idx_orders_tenant_status_created
    ON orders (tenant_id, status, created_at DESC);
```

## HTML / templates

`<!-- Visible to every browser: never put secrets or internal notes here. -->`
