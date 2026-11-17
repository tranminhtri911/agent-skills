# Review checklist by stage

Work top to bottom; a stage that finds a blocking design problem can stop the review early ("request changes: redesign first") instead of nitpicking code that will be rewritten. Domain detail lives in the owning skill — this list says *what to ask*, the skill says *what is right*.

## 1. Purpose and scope

- [ ] The change does what the ticket/acceptance criteria ask — no less, and nothing unrelated (AGENT-012). Extra refactors are split out or explicitly agreed.
- [ ] The PR description says why, how it was tested, and what is risky. Missing → ask before reviewing deeply.
- [ ] Maintenance/refactor: behavior outside the requested change is preserved, with baseline evidence (CHG-004/005, write-maintainable-code).

## 2. Design

- [ ] Belongs in this module/layer; follows the project's existing bases, helpers and reference module (CTX-009) instead of a parallel one.
- [ ] No speculative generality: no new layer, library, pattern or configuration point without a named problem (DES-007, DES-008).
- [ ] Data ownership is clear: who writes each table, which transaction boundary, which side effects (CTX-003).
- [ ] Contracts other code depends on (API, events, DB schema, shared types) change compatibly or with a migration path.

## 3. Behavior

- [ ] Edge cases: null/empty/zero, first/last page, duplicates, very large input, time zones, money rounding.
- [ ] Error paths: every failure is handled at the right boundary, reported, and leaves no partial state (TX-001, REL rules).
- [ ] Concurrency: two requests/jobs at once — lost updates, double processing, check-then-act races, lock order.
- [ ] Existing data and clients: old rows, nullable new columns, cached values, mobile clients on the previous version.
- [ ] Retries and re-runs: a job or request executed twice has one effect (idempotency).

## 4. Domain rules (load the owning skill)

- [ ] Database: queries match indexes; IDX-008 plan evidence for large/unbounded queries and bulk DML; migrations safe while the old app runs; no new FKs against policy.
- [ ] API: status codes, error envelope, pagination, versioning, idempotency keys.
- [ ] Security: authentication and authorization on every entry point, tenant filters, input validation, output encoding, secrets out of code and logs.
- [ ] Performance: bounded pools/queues, timeouts on remote calls, no N+1, no blocking calls in async code.
- [ ] Reliability: outbox/after-commit for side effects, bounded retries with backoff, unknown outcomes reconciled.
- [ ] UI: loading/error/empty states, accessibility, responsive targets, screenshots for visible changes.

## 5. Tests

- [ ] Each acceptance criterion and each risky path has a test; failure paths, not only the happy path.
- [ ] TEST-013: Check the scenarios against actual callers, supported limits, existing data and downstream outputs. Look for a realistic combination the suite could miss, and confirm any guard the change depends on at the relevant entry point.
- [ ] The test would fail if the code were broken (mutate the condition mentally — does an assertion catch it?).
- [ ] Assertions check outcomes (rows, responses, emitted events), not only "no exception".
- [ ] DB behavior (transactions, locks, migrations) tested on a real isolated engine, not a mock.
- [ ] No real money, email, SMS, paid API or shared server in tests (test-safely); no sleeps or order dependence.
- [ ] No test deleted, skipped or loosened to make the change pass.

## 6. Readability

- [ ] Names say what things are in domain words; no abbreviations a newcomer cannot decode (CODE-001).
- [ ] Domain values come from enums/constants/config, not bare literals (CODE-011).
- [ ] Functions do one thing; deep nesting and long parameter lists are justified.
- [ ] Comments explain why and state non-obvious contracts; none restate the code (DOC rules).

## 7. Style

- [ ] Only what the formatter/linter does not enforce. Prefer configuring the tool over repeating the same nit.

## Writing the review

- One finding per comment, most severe first; group repeated instances ("same at lines 40, 77, 102").
- Each `issue` carries a failure scenario and a fix; each `suggestion` says what it improves.
- Praise specific good decisions — it tells the author what to keep doing.
- Close with the verdict and what was not reviewed.

## Sources

- Google Engineering Practices — [The Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html), [What to look for](https://google.github.io/eng-practices/review/reviewer/looking-for.html): approve when code health improves; design first; tests must fail when code breaks.
- [Conventional Comments](https://conventionalcomments.org/): labels and blocking/non-blocking decorations.
- SmartBear, [Best Practices for Peer Code Review](https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/): the Cisco study's size and pace limits (about 200–400 lines per session, under about 500 lines/hour, 60–90 minutes); vendor-published figures, treat as guidance.
- [OWASP Code Review Guide v2](https://wiki.owasp.org/images/5/53/OWASP_Code_Review_Guide_v2.pdf): secure review method; 2017 edition — check current OWASP lists for the threat catalogue.
