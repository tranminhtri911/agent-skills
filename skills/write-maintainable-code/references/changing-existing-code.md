# Changing a complex running system: touch as little existing logic as possible (CHG-001..006)

Running code encodes behaviour nobody wrote down. Every edited line of it is a chance to break something the tests do not cover. On a complex or long-lived system, prefer adding new code next to the running logic, connected at one narrow point, and edit existing logic only where the behaviour must change. Use judgment: this is about risk, not a ritual. A one-line fix in well-tested code is simply made in place.

## Preservation contract for maintenance, updates and refactors (CHG-004/005)

- **Identify the old version before editing.** Record the resolved full commit ID, branch/ref for navigation, affected source paths/symbols, and any uncommitted changes. A branch name alone can move. For a dirty or uncommitted checkout, also pin the working-tree snapshot (`source_state.head` and `source_state.diff_digest` captured by `run-tests`); do not discard developer changes to obtain a clean baseline.
- **Read the old implementation and callers.** Trace inputs → branches → outputs/errors → state writes and external effects. Use actual old code as the baseline for behavior that must remain unchanged. Specs and tickets support the review; when they conflict with the code, record the discrepancy. Do not change existing behavior to match a spec unless the user's task authorizes that change.
- **Separate keep/change cases.** In the context map or task plan, record a compact table: case/input, old behavior and source, required behavior, authorized difference (if any), before/after evidence. For a pure refactor the authorized-difference column is empty. For a bugfix, only the requested defect changes; neighboring cases stay covered by preservation tests.
- **Compare observable behavior.** Include return/payload values and types, defaults, null/empty/invalid inputs, boundary amounts/dates, rounding/time zone, errors/statuses, state transitions, ordering and number of side effects, transaction/rollback and retry/idempotency behavior where relevant. Review the expanded call flow when extracting a wrapper; matching function names or signatures is insufficient.
- **Lock the comparison tests.** Run representative and boundary cases on the old implementation before editing, then the same assertions on the new one with the same synthetic fixtures, clock, seed, configuration and dependency versions. Review fixtures/configuration outside the test-source fingerprints explicitly. Compare pure old/new calculations directly when useful; never invoke real side effects twice. A test that should expose a requested bug may fail before the fix: keep it as a separate `regression` criterion, alongside passing preservation cases.
- **Report the evidence boundary.** Identify the old snapshot, preserved cases, intended differences, commands/results and anything not checked. If the old version cannot be executed safely or the baseline is missing, report source comparison separately and preservation as unverified; a passing build, lint, mock count or current-only suite does not establish equivalence.

## Decide: change in place or separate (judgment)

| Signal in the code you would touch | Lean to |
| --- | --- |
| The bug is in this logic; the change is small; tests cover it | **change in place**, minimal diff |
| Simple CRUD, glue code, code you added in this same task | change in place |
| Complex calculation (price, fee, tax, billing, payroll, points, schedule) or long branchy function | **separate**: new unit + seam |
| Many callers, money/permissions, weak or no tests, unchanged for a long time (`footprint` shows it) | separate, after characterization tests |
| A new rule that applies only from a date, to some tenants/plans, or behind a flag | separate, selected by date/tenant/flag |
| Rewrite you would like to do "while here" | neither: note it, propose it separately (design-change) |

When in doubt on a money or calculation path: separate, compare, then switch.

## Rules

- **CHG-001 plan the footprint.** Before editing, list the files/symbols you will change and why (in the plan or context map). `DS footprint --scope '<glob>' …` flags edits outside it; if findings require work beyond the user's request, propose it and wait for approval (CTX-007, AGENT-012). Review behavior inside planned files too; a matching path does not authorize unrelated changes.
- **CHG-002 add, don't rewrite.** Extend through the project's existing extension points first (new handler in the dispatch map, new enum case, subclass, event listener, config); otherwise one of the seams below. Running logic is edited only at the single connection point.
- **CHG-003 protected paths.** Code listed in `.devskills.toml` `[change] protected_paths` (e.g. `app/Services/Booking/BookingAmountCalculator.php`, `billing/**`) changes only with the user's explicit approval for this change, plus characterization tests; `footprint` fails otherwise (`--allow-protected` records the approval).
- **CHG-004 keep contracts.** Public function signatures, API fields, DB columns, events and queue payloads stay compatible: add optional parameters with defaults or a new function/field; deprecate before removing; never change the meaning of an existing name.
- **CHG-005 pin before touching.** Apply the preservation contract above to existing logic you must edit: identify the actual old source/snapshot, characterize representative and edge inputs, then retain before/after evidence. Use `preservation` (or `refactor`) criteria with the paired baseline schema in [refactoring-workflow.md](refactoring-workflow.md). Current-only passes cannot verify unchanged behavior.
- **CHG-006 never edit a migration that may have run anywhere**; add a new one.

## Seams (smallest first)

| Technique | Shape | Use when |
| --- | --- | --- |
| Sprout function/class | write the new logic as a new, fully tested unit; the old code calls it from one line | adding a step to a long function |
| Wrap | new function calls the old one unchanged and adds before/after behaviour | logging, validation, extra charge on top of the old result |
| New strategy/handler | register a new case in the existing map/enum/polymorphism | new type, plan or status with its own rule |
| Versioned unit + selector | `PriceCalculatorV2` beside V1; a selector picks by effective date, tenant or flag | changed calculation rules for a complex computation |
| Branch by abstraction / strangler | route one entry point at a time from old to new behind an interface | replacing a large legacy module over several releases |

## Separating complex calculation logic

1. **Freeze the old path.** Do not edit the existing calculator. Write characterization ("golden master") tests over a table of synthetic cases: inputs → today's outputs, including rounding, discounts, holidays, edge dates.
2. **New unit, pure.** Put the new rules in a separate class/module with explicit inputs and outputs, no DB writes, no I/O (easy to test exhaustively). Reuse the project's money/rounding helpers and enums (CODE-011).
3. **One selector.** Choose old or new in one place: by **effective date** for business rule changes (orders before the date keep old prices; recalculating an old booking uses the old rules), by tenant/plan, or by feature flag for rollout.
   ```python
   def calculate_booking_amount(booking: Booking) -> AmountBreakdown:
       """Single entry point; the rule set is chosen by the booking's pricing date (old bookings keep old rules)."""
       if booking.pricing_date >= settings.PRICING_V2_EFFECTIVE_DATE:
           return PricingV2().calculate(booking)
       return legacy_calculate_booking_amount(booking)  # unchanged
   ```
4. **Compare before switching** (when the new rules should reproduce the old results for unchanged cases): run both on the golden-master table in tests; optionally, in a non-production environment, compute both and log differences with the correlation id while returning the old result (shadow mode). Pure functions only; never double side effects.
5. **Switch and keep the old path** until the stop conditions pass (design-reliability `operability.md`); delete the old path in a later change, with its callers checked.

Laravel shape: `app/Services/Booking/Pricing/PricingV2.php` beside the existing `BookingAmountCalculator`, selected in one method; the controller and PDF services keep calling the same entry point.

## Evidence

- `DS footprint --base main --scope 'app/Services/Booking/Pricing/**' --run <id>` → new code vs existing lines removed, protected/out-of-scope/stable-code signals.
- Characterization tests green before and after, linked with `preservation`/`refactor` criteria; for a separated calculator the comparison table identifies intended differences as separate criteria (bugfixes tagged `regression`).
- The report states which existing files changed and why each was necessary.
