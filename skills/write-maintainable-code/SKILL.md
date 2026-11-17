---
name: write-maintainable-code
description: "Use when writing or modifying source code in any language — naming classes, methods, variables and constants, writing comments or docstrings, structuring functions and error handling, or reviewing code for readability and maintainability. Triggers (vi): viết hoặc sửa code, đặt tên biến/hàm, comment, docstring, code sạch, dễ bảo trì, refactor. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.1"
  suite: devskills
---

# Write Maintainable Code

Code is read far more than it is written: explicit names, small single-purpose functions, comments that explain why and state contracts, errors handled at the right boundary, always in the idiom of the repository's language and framework.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — this skill covers how code reads, not what it must do

What the code must do in each area comes from the domain skills; load them with the Skill tool before editing that part (dev-orchestrate's routing table): queries, transactions, deletes → change-database; endpoints → design-api; services and jobs → implement-backend; screens → implement-frontend; external calls → design-reliability; auth and input → review-security; concurrency and loops → review-performance; tests → test-safely. A full review of a diff or PR → review-code (this skill covers its readability stage).

Naming and casing per language, control-flow layout, lambdas, `static`, and when to apply repository/builder/interface/abstract/strategy/factory, per language and framework → **REQUIRED:** code-style. Load it together with this skill for every code change, new code and maintenance alike.

## Reuse the project's base first (CTX-009)

Before writing a class, helper, hook, component or error type, look for the one the project already has: the "Project conventions" section of `DS inspect` lists project-owned bases (`BaseModel`, `BaseRepository`, `BaseError`), shared modules, custom hooks, house decorators and a reference module of the same kind.

- Extend the existing base or helper; if it lacks something, add it there (one place) instead of writing a parallel version.
- Copy the reference module's layout, naming, error handling, logging and test style; consistency with the repo beats a "better" pattern from elsewhere.
- Names follow the project's existing vocabulary (`*Repository` vs `*Repo`, `get_` vs `fetch_`, `*Request` vs `*Dto`), even where the table below would choose differently.
- A new base, library or pattern needs a reason in the design (nothing existing fits) — never "I prefer it".

## No meaningless hard-coding (CODE-011)

Domain values — status, type, role, plan, error code, permission, limit, URL, timeout, user-facing text — come from the place the project defines them, never from a bare literal: `OrderStatus.PAID` not `"paid"`, `BookingStatus::CONFIRMED` not `'confirmed'`, `settings.PAYMENT_TIMEOUT_SECONDS` not `30`, the i18n key not the sentence.

- Look first: `inspect` lists the project's enums/choices/constant groups under "Project conventions"; also search the value and config/i18n/route/permission files.
- Missing and used twice, stored or sent over the API → add it where the project keeps such values, in its style, and use it throughout the change.
- Literals stay only in tests' expected payloads, migrations/seeds/fixtures, the definition itself and third-party protocol values.

Per-stack table, frontend/backend single source of truth and allowed exceptions: [no-hardcoding.md](references/no-hardcoding.md).

## Patterns and architecture: learn from the source, no over-engineering

- Learn first: `inspect` lists the **patterns in use** (Repository, Service, Action, FormRequest, `selectors.py`… with where they live) and the **pattern libraries/tools** the project has; read one request end to end in the reference module and the real import directions. The source's architecture is the spec.
- Each job uses the project's existing pattern (queries, rules, validation, side effects, wiring). A new pattern, layer or library only for a named problem in this change that the source has no answer for (DES-007, DES-008) — never Clean Architecture, Repository, Builder or a DI container "because it is best practice". When a pattern's signal is present (repeated data access, interchangeable providers, many optional constructor parts…), apply it as code-style's `references/patterns.md` describes.
- Keep the boundaries the source keeps: no imports against its layer direction, features talk through public modules, no cycles (ARC-003, ARC-007).
- Search before writing a helper; two copies are a note, three are extracted into the owning module (CODE-012).

Job → pattern table, over-engineering red flags, boundary tools, new-dependency checklist: [patterns-and-architecture.md](references/patterns-and-architecture.md).

## Touch as little running logic as possible (CHG-001..006)

For maintenance, updates and refactors, preserve every behavior outside the requested change. Before editing, identify the old commit plus working-tree snapshot, trace the actual old call flow, and list behaviors to keep versus explicitly requested differences. Existing code is the baseline for unchanged behavior; specs support the comparison but do not silently override it. CHG-005 requires before/after evidence, not just green tests on the new code. Read [changing-existing-code.md](references/changing-existing-code.md) for the comparison contract and [refactoring-workflow.md](references/refactoring-workflow.md) for paired `trace` evidence.

On a complex or long-lived system, judge each edit by risk: a small fix in well-tested code is made in place; complex calculation (price, fee, billing, schedule), many callers, weak tests or long-stable code → add a separate new unit (sprout, wrap, new handler, versioned calculator chosen by effective date/flag) connected at one point, with characterization tests on the old path. Plan the files you will touch, keep contracts compatible, never edit a migration that may have run, and leave protected paths alone without the user's approval. `DS footprint` measures new vs existing code touched. Decision table and seams: [changing-existing-code.md](references/changing-existing-code.md).

## Naming (CODE-001)

| Element | Rule | Example |
| --- | --- | --- |
| Class/type | Domain noun, PascalCase | `InvoicePaymentService`, `CreateOrderRequest` |
| Function/method | Verb + object, says the effect | `reserve_inventory` (Python), `reserveInventory` (TS/Java) |
| Boolean | Question/statement | `is_active`, `has_permission`, `can_retry` |
| Number with unit | Unit in the name or a type | `timeout_seconds`, `amount_minor`, `size_bytes` |
| Collection | Plural or mapping | `pending_jobs`, `orders_by_customer_id` |
| Enum/state | Finite domain | `PaymentStatus.PENDING` |
| ID | Kind and scope | `tenant_id`, `provider_payment_id` |

Follow the language convention (snake_case in Python, camelCase in JS/TS/Java, PascalCase methods in C#); the full casing tables per language and framework are in code-style. Avoid `data`, `tmp`, `obj`, `handleStuff`, `doIt` and abbreviations outside well-known ones (`id`, `url`, `db`). Name constants instead of magic numbers/strings — reusing the project's existing ones first (CODE-011).

## Comments and docs (DOC-001…006)

- Explain **why**, invariants, non-obvious decisions, and the contract: inputs/constraints, output, errors, side effects. Never narrate what the line obviously does.
- Public functions, business rules, transaction/lock/retry code and non-obvious algorithms get a short doc comment.
- DOC-003: follow the repository’s existing comment/doc conventions and language idioms. Use block comments or line comments as appropriate; Python uses `#` or docstrings, Go generally uses `//`. Only enforce a specific style when the project explicitly requests it through `[code].multiline_comment_style` (`off` by default). Templates are examples: [comment-templates.md](references/comment-templates.md).
- TODO needs an owner or issue: `TODO(tri): …` or `TODO(#123): …`. Delete commented-out code (git keeps history). Update comments with the code.
- Comment language follows the repository; identifiers in English.

## Structure

- One responsibility per function; length is a review signal (~60 lines), not a hard limit. Guard clauses instead of deep nesting.
- Side effects explicit at statements/boundaries — never hidden in conditions, comprehensions or render functions (CODE-004).
- No mutable default arguments, no hidden global state (CODE-006).
- Errors: catch at the boundary that can handle them, keep the cause, map to domain/system errors; never swallow, never "fix" by removing validation or returning success (CODE-007, CODE-008).
- Types explicit at public boundaries; no `any`/unchecked casts without validation (CODE-002).
- Separate refactors from features; keep diffs reviewable (CODE-009). Refactor procedure (characterization tests, call sites, small steps, scope control): [refactoring-workflow.md](references/refactoring-workflow.md). Never hand-edit generated files (CODE-010).

## Check it

`DS check-code` (changed files) or `DS check-code --paths src/feature` reports naming, comment style, docstring, exception, resource and security signals, and literals that repeat an existing enum/constant (`GEN-HARDCODED-DOMAIN-VALUE`). Treat findings as review signals: fix real problems; for a deliberate exception add `devskills:ignore RULE-ID reason` on that line. Project tuning lives in `.devskills.toml` (`[code] multiline_comment_style = "block" | "line" | "off"`, `max_function_lines`, `fail_on`).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| New `ApiClient`/`AppError` next to the project's own | Use and extend the existing one (CTX-009) |
| `if order.status == "pending"` while `OrderStatus` exists | `OrderStatus.PENDING`; new values go into the enum (CODE-011) |
| Same status list re-typed in backend and frontend | One source: API schema `enum` + generated types, or one constants module |
| `BaseRepository<T>` / interface / factory added for one use | Use the project's existing pattern; inline layers that only forward (DES-007) |
| Second HTTP client, date or state library | Use the one in the manifest; new dependency only with DES-008 checklist |
| New pricing rule written into the 1,400-line calculator | Separate `PricingV2` + one selector by effective date; old path frozen with golden-master tests (CHG-002) |
| `/* … */` block in a Python file | `#` lines, or a docstring at the top of the function |
| Comment repeats the code | Explain the business reason or constraint instead |
| `except Exception: pass` | Handle, log with context, or re-raise |
| `float` for money | Decimal or integer minor units + currency |
| One 300-line handler | Validate → authorize → use case → persist → map response, as separate functions |
