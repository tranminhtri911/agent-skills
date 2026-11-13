# Table design and naming conventions (defaults; follow the existing schema first)

## Naming

| Object | Convention | Example |
| --- | --- | --- |
| Table | lower snake_case, plural (or singular — one style per schema) | `orders`, `order_items` |
| Primary key | `id` | `id BIGINT` / `id UUID` |
| Reference column | `<entity>_id` | `order_id`, `tenant_id` |
| Boolean | `is_` / `has_` prefix | `is_active`, `has_invoice` |
| Time | `_at` for instants, `_on`/`_date` for dates | `paid_at`, `delivery_date` |
| Money | `_minor` integer or decimal + currency column | `total_minor`, `currency` |
| Index | `idx_<table>_<columns>` | `idx_orders_tenant_status_created` |
| Unique | `uq_<table>_<columns>` | `uq_orders_tenant_number` |
| Check | `ck_<table>_<rule>` | `ck_order_items_quantity_positive` |

## Template (PostgreSQL)

```sql
/*
 * orders: one row per customer order. Owner: orders module (service.py is the only writer).
 * Relations are logical (no FK by project policy): order_items.order_id → orders.id,
 * integrity owned by OrderService; orphan check job: jobs/reconcile_order_items.py.
 */
CREATE TABLE orders (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT      NOT NULL,
    number        TEXT        NOT NULL,
    status        TEXT        NOT NULL CHECK (status IN ('pending', 'paid', 'cancelled')),
    total_minor   BIGINT      NOT NULL CHECK (total_minor >= 0),
    currency      CHAR(3)     NOT NULL,
    version       INTEGER     NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ NULL,
    CONSTRAINT uq_orders_tenant_number UNIQUE (tenant_id, number)
);

/* Serves: list open orders of a tenant, newest first (orders/repository.py::list_open). */
CREATE INDEX idx_orders_tenant_status_created ON orders (tenant_id, status, created_at DESC) WHERE deleted_at IS NULL;
```

## Scale-up and maintainability checklist

- [ ] Key type fits growth and distribution (BIGINT identity vs UUIDv7) and index cost.
- [ ] Hot queries have supporting indexes; no index without a query.
- [ ] Large tables: archive/retention plan, partitioning only with evidence (DB-008).
- [ ] Wide JSON columns only for truly schemaless data; queried fields are real columns.
- [ ] Tenant column on every tenant-scoped table and in every unique key that must be per-tenant.
- [ ] Soft delete: unique constraints filtered by `deleted_at IS NULL`, default queries exclude deleted rows.
- [ ] PII columns identified; retention/deletion requirement known (DB-006).
- [ ] Every column documented in the migration comment or schema docs.
