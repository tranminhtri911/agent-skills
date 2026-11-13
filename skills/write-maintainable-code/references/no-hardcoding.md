# No meaningless hard-coding: reuse the project's values (CODE-011)

A literal that means something in the domain (a status, type, role, plan, facility, error code, permission, route, limit) must come from the one place that defines it. Repeating `'pending'` in ten files means the next rename, typo or new state silently breaks some of them, and nothing (typecheck, tests, search) reliably finds them all.

## 1. Find what already exists (before writing the literal)

- `DS inspect --feature <words>` → "Project conventions to reuse" lists **values** (enums, `TextChoices`, backed enums, `as const` objects, `STATUS_*` constant groups) and **key constants** (`USER_ID = "user_id"` style) with where they are defined.
- Search the value itself: `rg -n "['\"]pending['\"]"` and the likely type name (`Status`, `Type`, `Kind`, `Role`, `Mode`); with CodeGraph, `codegraph explore OrderStatus`.
- Also check: settings/config (`settings.py`, `config/*.php`, `appsettings.json`, `.env.example` keys), i18n catalogues, route names, permission/role tables, design tokens (colours, spacing), shared `constants/` modules, the OpenAPI schema (`enum:`) and generated clients.

## 2. Use it

| Stack | Instead of | Use |
| --- | --- | --- |
| Django model/query | `status="paid"`, `if order.status == "pending"` | `OrderStatus.PAID`, `order.status == OrderStatus.PENDING` |
| Django field | `CharField(choices=[("pending","Pending"), ...], default="pending")` | `CharField(choices=OrderStatus.choices, default=OrderStatus.PENDING)` |
| DRF | `ChoiceField(choices=["pending", "paid"])` | `ChoiceField(choices=OrderStatus.choices)` |
| Laravel | `->where('status', 'confirmed')`, `$x === 'sbf'` | `->where('status', BookingStatus::CONFIRMED)`, `$booking->facility === Facility::SBF` (model `casts` to the enum) |
| Laravel validation | `'in:sbf,kbf'` | `Rule::enum(Facility::class)` |
| Laravel labels | `['sbf' => 'SBF', 'kbf' => 'KBF']` in a controller | a `label()` method on the enum, or the translation file keyed by the enum value |
| React/TS | `order.status === 'paid'` | `order.status === OrderStatus.Paid` from the project's constants module or the generated API types |
| TS types | `status: string` | `status: OrderStatus` (union or enum generated from OpenAPI when the project generates types) |
| C# | `order.State.ToString() == "Submitted"` | `order.State == OrderState.Submitted` |
| Any | `timeout=30`, `page_size=50`, `"https://api.example.com"` | the setting/config value the project already reads (`settings.PAYMENT_TIMEOUT_SECONDS`, `config('services.x.url')`) |
| Any | user-facing text in code | the i18n key the project uses (`_("…")`, `__('…')`, `t('…')`) |
| Any | `if user.id == 1`, `tenant_id = 3` | a role/permission check or a configured id; never a database row id in code |

Comparisons, queries, defaults, validation rules, switch/match arms, serializer choices, response mapping and frontend conditions all use the named value.

## 3. When nothing exists yet

- A value used once, whose meaning is obvious from the line (`range(3)` for three retries named `max_attempts`, `0`, `1`, `""`, an HTTP status via the framework's constant) needs no new type — but name it if a reader would ask "why this number?".
- A domain value used in two or more places, or stored in the database, or sent over the API → create the enum/constant **where the project keeps them** (the reference module shows it: `app/Enums/`, `models.TextChoices` next to the model, `src/constants/`), in the project's style, and use it everywhere in your change.
- Backend and frontend each need it → one source of truth: the API schema (`enum:` in OpenAPI) with generated frontend types if the project generates them; otherwise a single frontend constants module mirroring the backend, named the same.
- Two enums already hold the same values (`PaymentMode.FIRST_PAYMENT` and `RegisterPaymentCase.FIRST_PAYMENT`) → use the one the surrounding code uses; propose merging them separately (refactor), not inside the feature diff.

## 4. What may stay literal

- Test inputs and expected API payloads: the contract *is* the string (`assert response.json()["status"] == "paid"`); still use the enum for arrangement data where natural.
- Migrations, seeders, factories, fixtures and translation files: they record values at a point in time.
- The enum/constant definition itself, and log/exception text.
- Third-party protocol values that are not your domain (`payment_method_types: ["card"]` for Stripe): name them as a constant if repeated; otherwise a deliberate literal is fine (`devskills:ignore GEN-HARDCODED-DOMAIN-VALUE Stripe API value`).

## 5. Check it

`DS check-code` reports `GEN-HARDCODED-DOMAIN-VALUE` when a changed file compares, queries or assigns a literal that equals a value of an existing enum/constant group of the same language (medium when the line names the domain, e.g. `status`; low when only compared). Fix by using the named value; suppress with a reason only for the cases in section 4. Turn it off per repo with `[code] hardcoded_values = false` in `.devskills.toml`.

Review question for every literal in the diff: "If this value is renamed or a new one is added, will this line be found and updated?" If not, it should be the named value.
