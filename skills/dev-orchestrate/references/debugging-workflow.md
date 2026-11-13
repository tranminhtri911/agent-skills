# Debugging workflow: reproduce → trace → hypothesis → root-cause fix → regression test

A bug is fixed when a test that failed for the reported reason now passes, and nothing near it broke. Changing code until the symptom disappears is not a fix.

## 1. Reproduce

- Write down the exact report: input, user/tenant/role, environment, time, expected vs actual, correlation id or log line.
- Reproduce locally with the smallest input. Best form: a failing automated test at the lowest layer that shows the bug (unit → API → E2E).
- Data-dependent bugs: rebuild the shape of the data with synthetic fixtures; never copy production data or connect to production (dangerous operations).
- Cannot reproduce → collect more evidence (logs around the correlation id, versions, feature flags, timezone, concurrency) instead of guessing. Report "not reproduced" honestly.
- Flaky: `DS run-tests --retries 3` classifies it; look for shared state, ordering, time, randomness, races.

## 2. Trace the flow

- discover-codebase: entry point → callers → data → side effects; all writers of the affected table.
- Read the actual code path for the reproducing input; add temporary logging or a debugger breakpoint rather than reasoning from names.
- `git log -p -- <file>` / `git blame` on the suspicious lines; `git bisect` with the failing test when it used to work (read-only for history; no rewriting).
- Compare with a working sibling case (other tenant, other status, other browser): the difference narrows the cause.

## 3. Form and test hypotheses

Write each hypothesis with the observation that would prove or refute it, then run the cheapest experiment:

| Hypothesis | Experiment | Result |
| --- | --- | --- |
| Timezone: date compared in local time | run test with `TZ=Asia/Tokyo` and UTC | fails only in JST → confirmed |
| Race: two workers process the same item | test with two threads + barrier | duplicate created → confirmed |

One change at a time. Keep refuted hypotheses in the notes: they stop the next person from repeating them.

## 4. Fix the root cause

- Fix where the wrong behaviour originates (the shared use case, the query, the boundary that should validate), not where the symptom appears (one screen, one caller).
- Check whether the same mistake exists in siblings (search for the pattern) and on other paths (admin, worker, import).
- Never "fix" by: removing validation, widening permissions, swallowing the exception, adding a retry around a non-idempotent call, bumping a timeout without understanding, or editing the test to match wrong output.
- Data already damaged by the bug: write an idempotent, dry-run-first repair script and ask before running it anywhere but local.

## 5. Regression tests

- The reproducing test from step 1 is now green and stays in the suite with a name that states the rule (`test_order_date_uses_tenant_timezone`).
- Run the tests around the fix: same module, callers found in step 2, and the affected tests from CodeGraph when available; then `DS native-checks --execute`.
- Report: cause (with evidence), fix, tests added, what was not verified, and whether data repair is needed.

## Evidence in the run

`trace` acceptance criterion for a bug: `{"id": "BUG-123", "text": "order date uses tenant timezone", "tags": ["regression"], "evidence": [{"test": "orders/tests/test_dates.py::test_order_date_uses_tenant_timezone", "check": "tests.unit"}]}`.
