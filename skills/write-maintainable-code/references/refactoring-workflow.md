# Refactoring workflow: same behaviour, less complexity, controlled scope

A refactor changes structure, never behaviour. If behaviour must change too, do it in a separate step (separate commit/PR) after the refactor is proven safe.

## 1. Pin the current behaviour

- Apply the [preservation contract](changing-existing-code.md#preservation-contract-for-maintenance-updates-and-refactors-chg-004005): pin the old commit/snapshot, read actual source and callers, and list the behavior to keep. Specs cannot override existing behavior outside the requested change.
- Find the tests that cover the code; if coverage is thin, write **characterization tests** first: call the code with representative and edge inputs and assert today's outputs, errors and side effects (even odd ones — note them, do not fix them now).
- Record the baseline in a separate run: `DS run start --risk R1 --label baseline`, then `DS native-checks --execute --run <baseline-id>` and the relevant `DS run-tests --run <baseline-id> --junit <report> -- <test command>`. Copy the captured `details.source_state` from the test check into the acceptance criterion below. Preserve the baseline run; use a new run for implementation/current checks. Do not add the old baseline check to the current roster: it intentionally describes old code.

## 2. Map every call site

- `DS inspect --feature <name>` lists callers; with CodeGraph: `codegraph callers <Symbol>` and `codegraph impact <Symbol> --depth 2`.
- Also search what static tools miss: string references (`getattr`, route names, `reverse("...")`, serializer field names, templates, `$this->{$method}`), reflection/DI registrations, generated clients, public API/SDK consumers, cron/queue job names, database views or triggers that reference renamed columns.
- Public or cross-service interfaces: keep the old name as a deprecated alias for a transition period instead of renaming everywhere at once.

## 3. Change in small, verifiable steps

| Smell | Move |
| --- | --- |
| Duplicated logic in 2+ places | extract one function in the module that owns the rule; replace call sites one by one |
| Long function (> ~60 lines, many branches) | extract steps with intention-revealing names; guard clauses for early exits |
| Deep conditionals on a type/status | lookup table or polymorphism — only if a third case exists or is planned |
| Long parameter list / data clumps | a small typed object (dataclass, DTO) already used by the project if one exists |
| Business rule in view/serializer/component | move it into the use case/service; the old place calls it |
| God class | split by responsibility along the boundaries callers already use |

After each step: run the focused tests. Commit-sized steps make a failing step easy to find and revert (reverting your own uncommitted work in progress is fine; discarding others' changes is a dangerous operation).

## 4. Control the scope

- Touch only what the goal needs; note other smells for later instead of fixing them in passing.
- No formatting sweeps, renames or dependency upgrades mixed into a refactor diff (CODE-009); they hide real changes from review.
- Keep the project's patterns (CTX-009): a refactor is not the place to introduce a new architecture.
- When the call-site map reveals work beyond the user's request, propose the expansion and wait for approval (CTX-007, AGENT-012); `DS footprint --scope '<glob>'` shows file edits outside the plan, while behavior changes inside planned files still need review.
- On complex running logic, decide refactor vs leaving it and adding beside it (changing-existing-code.md): a refactor is justified by the change it enables, not by taste.

## 5. Prove it

- The same tests (characterization + existing) pass before and after; no test was edited to match new output. If one had to change, that is a behaviour change — explain it or revert.
- `DS native-checks --execute` (typecheck catches missed call sites), `DS check-code`, and for DB-touching code the query count assertions.
- Complexity went down measurably: fewer duplicates, shorter functions, fewer branches — mention numbers in the report.
- Link the same exact testcase in the current check to a separate recorded baseline run. Use tag `refactor` for a pure refactor, or `preservation` for unchanged cases during maintenance/update/bugfix. Example schema (placeholders are illustrative, not execution evidence):

  ```json
  {
    "id": "RF-1",
    "text": "order total calculation behaviour unchanged",
    "tags": ["refactor"],
    "preservation": {
      "baseline_run": "<baseline-id>",
      "baseline_check": "tests.unit",
      "baseline_state": {
        "head": "<full-commit-id-or-null>",
        "diff_digest": "<captured-SHA-256>"
      }
    },
    "evidence": [{
      "test": "orders/tests/test_totals_characterization.py::test_totals_match_baseline",
      "check": "tests.unit"
    }]
  }
  ```

  Copy `baseline_state` exactly from the baseline check's `details.source_state`; `head` is JSON `null` for an uncommitted repository. `trace` requires the named test to pass in both completed checks, the baseline to finish before the current execution, and complete test-source fingerprints that remain unchanged. Newly added test files are allowed; changing/removing baseline assertions or helpers invalidates the comparison. Legacy checks without fingerprints, current-only passes, check-only evidence and missing baseline identity stay `unverified`; a failed baseline stays `failed`.
- Fingerprints cover conventionally named test/helper **source** files recognized by the runtime (e.g. under `tests/`), not external fixtures/configuration, dependencies or business semantics. Oversized/unreadable files or truncated discovery cannot provide preservation proof. Review the keep/change table and old/new call flows even when `trace` passes. An untagged claim or omitted preservation criterion cannot be inferred reliably from a code diff; the agent must include every relevant claim.
