# SQL style

Applies to migrations, stored procedures, views and raw queries. The repository's existing schema naming and SQL formatter (sqlfluff, pg_format) win over this page; data rules (transactions, locks, indexes, deletes) live in change-database.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Table | `snake_case`, the repository's singular/plural choice | `invoice_lines` |
| Column | `snake_case`, full words | `created_at`, `amount_minor` |
| Primary key / foreign reference | `id` / `<entity>_id` | `customer_id` |
| Boolean column | `is_`/`has_` | `is_active` |
| Index / constraint | the repository's scheme; otherwise one consistent scheme naming type, table and columns | `ix_invoices_customer_id`, `uq_users_email` |

No abbreviations, no reserved words as names, no quoted identifiers that need case-sensitive quoting.

## Layout

- Keywords in UPPERCASE, identifiers in lowercase (unless the repository does the opposite consistently).
- One clause per line (`SELECT`, `FROM`, `JOIN`, `WHERE`, `GROUP BY`, `ORDER BY`); each selected column on its own line when there are more than a few.
- Explicit `JOIN … ON` instead of comma joins; explicit column lists instead of `SELECT *` in application code and views.
- Table aliases that mean something (`invoices AS inv`), not `a`, `b`, `c`.

```sql
SELECT
    inv.id,
    inv.total_minor,
    cus.display_name
FROM invoices AS inv
JOIN customers AS cus ON cus.id = inv.customer_id
WHERE inv.status = 'paid'
ORDER BY inv.created_at DESC;
```

## Readability over cleverness

Common table expressions (`WITH paid_invoices AS (…)`) with descriptive names instead of nested subqueries; a comment on non-obvious business filters.

## Sources

- [SQL Style Guide (Simon Holywell)](https://www.sqlstyle.guide/)
