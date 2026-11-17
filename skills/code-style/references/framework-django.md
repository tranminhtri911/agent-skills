# Django style

Builds on [Python style](language-python.md); the project's own app layout and settings win. Data rules (migrations, transactions, deletes) live in change-database.

## Names and files

| Element | Style | Example |
| --- | --- | --- |
| App | short, plural or domain noun, `snake_case` | `invoices` |
| Model | singular `CapWords` | `Invoice`, `InvoiceLine` |
| Model field | `lower_snake_case` | `created_at`, `amount_minor` |
| View (function) / view class | verb + noun / noun + `View` | `create_invoice`, `InvoiceDetailView` |
| URL name | `app:action` | `invoices:detail` |
| Template | `app/<model>_<action>.html` | `invoices/invoice_detail.html` |

## Model layout

Order inside a model: fields; custom manager attributes; `class Meta` (after the fields, one blank line); `__str__`; `save`; `get_absolute_url`; custom methods (Django coding style).

## Where logic goes (patterns by signal)

- Query logic used by more than one caller → a custom `QuerySet`/`Manager` method (`Invoice.objects.overdue()`), the Django form of a repository. A separate repository class only if the project already has that layer.
- Business operations spanning several models → a function in `services.py` (or the project's equivalent), wrapped in `transaction.atomic`.
- Read-only query composition → `selectors.py` if the project uses it.
- Views stay thin: validate (form/serializer) → call the service → render/serialize.

## Explicit over clever

- No logic in templates beyond display; no `QuerySet` chains longer than a few calls without a named method.
- `select_related`/`prefetch_related` named where the view needs them, not hidden in a generic mixin.
- Settings through `django.conf.settings`, never hard-coded values.

## Sources

- [Django coding style](https://docs.djangoproject.com/en/stable/internals/contributing/writing-code/coding-style/)
- [Django managers](https://docs.djangoproject.com/en/stable/topics/db/managers/)
