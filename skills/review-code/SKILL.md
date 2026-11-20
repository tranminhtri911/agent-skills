---
name: review-code
description: "Use when reviewing a code diff, PR, commit or implementation for behavior, safety and regression risk. Triggers (vi): review code, review PR, xem diff, tự review, kiểm tra code trước khi merge."
metadata:
  version: "1.0.8"
  suite: devskills
---

# Review Code

A review decides whether a change makes the codebase healthier and is safe to ship, and says exactly what must change before merge. Approve once the change clearly improves code health and meets its requirement, even if it is not how you would write it; block on defects, risk and maintainability problems — never on taste (REV-001).

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — the domain skills are the checklists

This skill is the method; the rules come from the skill that owns each area of the diff. Before reviewing that part, load it with the Skill tool and review against its rules, citing their IDs (REV-005).

| The diff touches | Load | Look especially for |
| --- | --- | --- |
| queries, ORM, repositories, migrations, stored procedures, deletes, transactions, locks | change-database | atomicity and rollback, lock scope, N+1, IDX-008 plan evidence for large tables, migration vs running app |
| endpoints, request/response, errors, webhooks | design-api | breaking changes, error format, idempotency, authorization |
| services, jobs, batches, uploads | implement-backend | validate → authorize → use case path, job re-runs |
| screen or component implementations | implement-frontend; verify-ui for rendered checks | loading/error/empty states, accessibility, screenshots |
| auth, sessions, tenants, user input, secrets, payments | review-security | injection, missing authorization, tenant leaks, secrets in code |
| threads, async, workers, caches, loops over many rows | review-performance | unbounded resources, blocking calls, missing timeouts |
| external calls, retries, queues, job locks | design-reliability | duplicates, partial failure, unknown outcomes |
| tests, seeds, fixtures | test-safely | tests that cannot fail, real side effects, mocked DB for DB behavior |
| names, comments, structure | write-maintainable-code, code-style, code-documentation for new code or explicitly requested comments | doc comments that state behavior the code does not have or that the change made outdated, redundant comments, unclear names, literals instead of enums, over-engineering, one-line `if`, opaque lambdas, needless `static`, a pattern missing where its signal is present |
| Terraform, IAM, networks | design-infrastructure | wildcard permissions, public exposure |

## Procedure

1. **Purpose first (REV-002).** Read the ticket, acceptance criteria and PR description; know what the change must do before judging how. None given: ask, or state the assumed purpose at the top of the review.
2. **Size (REV-003).** `git diff --stat <base>...HEAD` and `DS footprint --base <base>`. Over about 400 changed lines of logic: review in passes, one per hand-off row, and recommend splitting. Reading faster than about 500 lines/hour misses defects.
3. **Context.** Read the whole function and file around each hunk, the callers of every changed signature and the data it writes (discover-codebase, CTX-001) — a correct-looking hunk can break a caller you did not open.
4. **Read in order of impact (REV-004):** design (belongs here, fits the project's bases and layers, not over-engineered) → behavior (edge cases, null/empty, concurrency, error and partial-failure paths, existing rows and old clients) → domain rules (hand-off table) → tests (would they fail if the code were broken? failure paths covered?) → readability → style that no linter covers. Checklist per stage: [review-checklist.md](references/review-checklist.md).
5. **Run the tools as evidence, not as the review (REV-008):** `DS native-checks --execute`, `DS check-code`, `DS check-sql`, `DS scan-secrets`, the project's tests through test-safely. A clean run means "nothing found in the checked scope".
6. **Confirm every finding (REV-006):** location plus a concrete failure scenario — input or state → wrong result — confirmed in the code or by a test you ran. If you cannot build one, it is a `question`, not an `issue`.
7. **Write findings and a verdict (REV-007, REV-008)** in the format below, most severe first.

## Finding format (Conventional Comments)

```
<label> (<blocking|non-blocking>, <severity>): <one-line claim> — path/to/file.ext:line
Why: <failure scenario, or the rule ID it breaks>
Fix: <concrete change; short code when it helps>
```

Labels: `issue` (a defect — blocking at critical/high), `suggestion` (a better way; non-blocking unless it prevents an issue), `question` (intent unclear; never blocking), `nitpick` (never blocking), `todo` (small required follow-up), `praise` (name what is good when it is). Severity: **critical** — data loss or corruption, security hole, money, outage; **high** — wrong behavior on a realistic path; **medium** — edge case, missing test on a risky path; **low** — everything else.

```
issue (blocking, high): survey delete runs one DELETE over all answers with no plan evidence — db/procs/DeleteSurvey.sql:41
Why: Answers has ~8M rows; the WHERE on SurveyId is not indexed, so the statement scans and holds locks for minutes while the send job writes (IDX-008, TX rules).
Fix: index (SurveyId) or reuse IX_Answers_Survey; delete in chunks of 5,000 by Id with a commit per chunk; attach the estimated plan.
```

Verdict, last line: **Approve** / **Approve with comments** (non-blocking only) / **Request changes** (any blocking) — plus what you did not review (files skipped, checks that could not run).

## Your own and AI-written changes (REV-009)

Before reporting your own change done, review its diff with this skill as if someone else wrote it. For AI-generated code also check: every API, symbol, config key and package version exists in the installed version (AGENT-006); nothing outside the requested scope (AGENT-012); tests assert behavior and none were deleted, skipped or loosened to pass.

## Someone else's PR (REV-010)

Comment on the code, not the person; say why; ask when intent is unclear. Posting comments, approving, pushing to their branch and merging are outward-facing: draft the review locally, show it, and post or merge only when the user asks.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Reviewing only the hunks | Open the whole function, its callers and the data it writes |
| A flood of style nits, the data-loss bug missed | Impact order: design → behavior → domain → tests → readability |
| "Looks wrong" with no scenario | Build the failing input or state, or ask a `question` |
| Blocking on taste | Approve when code health improves; label preferences `nitpick` |
| "Tests pass" taken as proof | Ask whether the tests would fail if the code were broken |
| Reviewing DB, API or security parts from memory | Load the owning skill and cite its rule IDs |
| Silent about what was not checked | The verdict lists skipped files and checks that did not run |
