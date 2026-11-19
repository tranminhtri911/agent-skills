---
name: test-safely
description: "Use when planning, writing or running tests, test scripts or test data (SQL seeds, e2e), reproducing a bug, or verifying a change — especially anything touching money or payments, batch jobs, emails/SMS/push, paid or third-party APIs, production-like data, load or performance tests, migrations, or shared servers. Triggers (vi): viết test, chạy test, unit test, e2e, mock, dữ liệu giả, tái hiện lỗi, kiểm thử thanh toán/batch/email. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.5"
  suite: devskills
---

# Test Safely

Tests prove behavior with evidence, and they can never charge money, message real people, create cloud resources, load shared servers or touch production data. Safety is enforced by the runner, not by good intentions.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Tests that prove transactions, locks, deletes or migrations (real isolated engine, never a mocked DB) → **REQUIRED:** change-database.
- Payment, email or external-provider failure paths → **REQUIRED:** design-reliability.
- Any UI E2E run, screenshots or visual baselines → **REQUIRED:** `verify-ui`, which routes to the available `ui-ux-pro-max` for UX review.
- Running a task's E2E or manual test cases by checklist with per-step screenshots and OK/NG evidence → **REQUIRED:** `e2e-evidence`.

## Profiles

Cloud access requires the warning and explicit approval in dev-orchestrate OPS-011 before any test, script or tool uses a cloud profile, key, token, service account, SSO session or ambient credentials, including read-only and identity/connection checks. `provider_sandbox`, `--allow-host` and a general request to test are not cloud approval. Inspect credential discovery and SDK calls before execution; default to credential-free local mocks. Approval for a cloud connection does not waive the test isolation, no-real-payment or other safety restrictions below.

Every non-local database connection or operation requires the warning and explicit approval in OPS-012, including SELECT, schema/plan inspection, health/connection checks and backups through apps/scripts/tests, existing sessions or localhost tunnels. A general request to test is not approval; do not connect to validate an unknown target first. Use disposable confirmed local databases. Approval for remote DB access does not waive the profiles' prohibition on shared/staging/production test data or outbound access.

| Profile | Allowed | Not allowed |
| --- | --- | --- |
| `unit_offline` (default) | pure unit tests, fakes, fake clock, local fixtures | network beyond loopback, credentials, side effects |
| `integration_isolated` | disposable DB/cache/queue containers on this machine, synthetic data | shared/staging/production data, outbound Internet |
| `provider_sandbox` | a provider sandbox the user explicitly approved (`--allow-host`) | live mode, real people, cost beyond budget |
| `performance_isolated` | bounded load on local test resources | load on production or guessed targets |

## What to use for dangerous things

| Thing | Use | Never |
| --- | --- | --- |
| Payments, refunds, payouts | `DS simulate payment` or provider test mode | live keys, real cards |
| Email/SMS/push | simulator outbox (`/v1/messages`) or a local catcher (Mailpit) | real recipients |
| Paid/third-party APIs | fakes, recorded fixtures, simulators | real calls in CI |
| Database behavior (transactions, locks, migrations, indexes) | real engine of the same version in a disposable container | SQLite/mocks as proof of PostgreSQL/MySQL behavior |
| Batch jobs | small synthetic datasets, fault injection at item N, resume tests | production data, full-size runs on shared DBs |
| Load/performance | `performance_isolated` against localhost | production, shared staging, paid APIs |

Mocks prove interactions; fakes prove simple domain behavior; stateful simulators prove timeouts/duplicates/out-of-order; only a real disposable DB proves SQL/locking/migrations (plan §18.3).

## Procedure

1. **Preflight**: `DS preflight [--run <id>]` — blocks live keys, production markers and non-local DB/queue/SMTP hosts in the env files the tests may load.
2. **Run through the safe runner**:
   `DS run-tests --profile unit_offline --check-id tests.unit --junit reports/junit.xml [--run <id>] -- python -m pytest -q --junitxml=reports/junit.xml`
   It passes only allowlisted environment variables (secrets are stripped; add one with `--env NAME`), forces `TZ=UTC`, uses macOS OS network isolation when available plus a partial Python socket guard. Integration/performance/provider profiles fail closed without an applicable OS wrapper; unit_offline alone may use the partial guard for trusted pure tests. This is not a filesystem/credential sandbox, and native tools can bypass the Python guard, kills the whole process tree on `--timeout`, caps and redacts logs, rejects stale reports, and maps results honestly: no tests collected → blocked, any unparseable/non-JUnit report → blocked, exit 0 without a report → warn, pass only after retry → flaky (blocked). Parsed evidence records each testcase's file, class, exact name and outcome; skipped or unrecorded tests cannot be verified by linking them to a passing check.
3. **Integration**: start disposable services yourself (e.g. `docker compose -f docker-compose.test.yml up -d`), then `DS run-tests --profile integration_isolated --check-id tests.integration …`. Never point tests at a database you did not create for the run.
4. **Native tools**: `DS native-checks` shows the project's typecheck/lint/build/framework commands (from package.json scripts, pyproject, manage.py, composer, go.mod, Cargo, csproj, Makefile); `--execute --run <id>` runs them through the same safe runner. They never download tools, refuse scripts with deploy/publish/network side effects, and report missing dependencies as blocked.
5. **Record** results into the run (`--run <id>`) so `DS report` can aggregate them.

Test selection, required cases and examples: [test-matrix.md](references/test-matrix.md). With the optional CodeGraph integration, start from the graph's list of affected tests: `code_graph.affected_tests` in the context map from `DS inspect`, or `codegraph affected --json <changed files>`. Then add the tests the risk level requires; an empty list means "no covering test found", not "nothing to test".

For every UI E2E run, include a rendered layout check for the screens and states exercised, even if the request only says to run E2E. Use `verify-ui` and the available `ui-ux-pro-max` to check for horizontal overflow, overlap, clipping, text wrapping, controls moving to another row and added rows/items at target widths and affected breakpoints. Use targeted DOM assertions where the expected layout can be expressed reliably, and open the rendered screen or captures to judge visual reflow. During implementation, reproduce and fix confirmed layout regressions within the task scope and rerun the failing case and nearby widths. In a test-only run, record the defect and reproduction evidence. Include long content and enough synthetic items to trigger wrapping or scrolling where relevant. Passing clicks/text assertions does not establish layout quality; report behavior results and the layout inspection evidence separately, including any layout checks not performed.

Also report unusual UI or UX that conflicts with the established product context, target users/roles or business flow (for example SaaS workspace/billing context or end-user task clarity). Include evidence, user impact and a suggested improvement or clarification; distinguish confirmed defects from uncertain concerns and optional suggestions. Report these findings even when tests pass, without expanding the task into an unrequested redesign or business-rule change.

## Rules (TEST-001…TEST-013, SAFE-001…SAFE-013)

- Every important acceptance criterion maps to a test or review evidence; bugfixes get a regression test when reproducible safely.
- Assert behavior and invariants, not mock call counts.
- Money/auth/concurrency/transactions need negative and failure-path tests.
- **TEST-013:** For business behavior, use the [scenario review](references/test-matrix.md#derive-scenarios-from-the-real-flow) during analysis and before handover. Establish which source defines expected behavior, test assumptions relied on by the change, and record the outcomes and coverage gaps. Use production-shaped synthetic fixtures in isolation under the profiles above.
- Control seed, clock, IDs, locale and time zone.
- Never delete, skip or xfail tests to get green; quarantine needs owner and expiry; a retry that passes is still flaky.
- A required test that did not run is `blocked`/`not_run`; collection errors are not passes.
- Record failures that existed before the change separately from new regressions.
- For unchanged legacy behavior, run the same assertions on an identified old snapshot and the new code in separate runs; tag criteria `preservation`/`refactor` and link `preservation.baseline_run`, `baseline_check` and `baseline_state` (copy `details.source_state` from the baseline check). `run-tests` records `source_state` plus test-source hashes before/after report-producing commands. These detect altered test sources, not changed external fixtures/configuration or semantic coverage: review those explicitly. Missing before/after evidence stays unverified. Keep bugfix `regression` criteria separate: they may intentionally fail on old code. Detailed workflow when write-maintainable-code is available: its `references/refactoring-workflow.md`, section 5.
- Cleanup removes only resources created by the run; never wildcard deletes on shared servers.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `.env` points at staging and the framework loads it in tests | Use `.env.testing`/test settings; preflight blocks it |
| Mocking the DB to test a race condition | Two concurrent sessions against a real disposable DB |
| `sleep(2)` to wait for async work | Poll a condition with a deadline |
| Asserting the email "was sent" via mock count | Assert the outbox content in the simulator |
