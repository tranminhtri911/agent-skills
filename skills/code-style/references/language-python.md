# Python style

Frameworks: [Django](framework-django.md), [FastAPI](framework-fastapi.md). Repository tooling (ruff, black, isort, flake8, pylint config in `pyproject.toml`/`setup.cfg`) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Module, package, file | `lower_snake_case` | `invoice_service.py` |
| Function, method, variable, parameter | `lower_snake_case` | `calculate_invoice_total`, `retry_count` |
| Class, exception, type alias | `CapWords` | `InvoiceService`, `PaymentDeclinedError` |
| Constant (module level) | `UPPER_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |
| Internal (not public API) | leading `_` | `_parse_row` |
| Boolean | `is_`/`has_`/`can_`/`should_` | `is_expired` |

Exceptions end in `Error` when they are errors. Avoid one-letter names except short loop indexes and well-known math.

## Layout

- One statement per line; the body of `if`/`for`/`while`/`with` on the next line, never `if x: return y` on one line (PEP 8 discourages compound statements).
- Guard clauses first, then the main path. A conditional expression (`a if cond else b`) only for a simple value choice, never nested.
- Imports at the top, grouped standard library → third party → local.

## Lambdas, comprehensions, chains

- A lambda only inline for a one-expression key or predicate. Never bind a lambda to a name: write `def` (PEP 8).
- Comprehensions: one `for` and at most one `if`; multiple `for` clauses or nested comprehensions become loops (Google Python Style Guide).
- Prefer a named helper over `map`/`filter` with a lambda.

```python
# Not this
by_total = lambda orders: sorted([o for c in customers for o in c.orders if o.paid], key=lambda o: -o.total)

# This
def paid_orders_by_total_descending(customers: list[Customer]) -> list[Order]:
    paid_orders = []
    for customer in customers:
        for order in customer.orders:
            if order.is_paid:
                paid_orders.append(order)
    return sorted(paid_orders, key=lambda order: order.total, reverse=True)
```

## Static and class-level members

- Prefer a module-level function to `@staticmethod`; use `@staticmethod` only when an existing API requires it (Google Python Style Guide).
- `@classmethod` for alternative constructors (`Invoice.from_row(row)`).
- No mutable class attributes shared by instances (`items = []` at class level); initialise in `__init__` or use `dataclasses.field(default_factory=list)`.
- Module-level singletons holding clients or connections are created by the app's factory/DI, not at import time.

## Types and contracts

Type hints on public functions and methods; `dataclass`/`pydantic` models for structured data instead of loose dicts; docstrings for public functions (write-maintainable-code).

## Sources

- [PEP 8 — Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (lambdas, comprehensions, `staticmethod`)
