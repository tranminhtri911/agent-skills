---
name: dev-orchestrate
description: "Use when working on any development task or ticket for an application (backend, frontend, API, database, jobs, infrastructure), in any language — requirements, impact or feasibility, planning or specifying, implementing a feature, bugfix or refactor, tests, review, commit or reporting results. Triggers (vi): làm task, ticket, thêm chức năng, sửa lỗi, triển khai, phân tích tác động, viết spec, test, review, commit, báo cáo kết quả. Applies even when the request is phrased as a question (\"làm sao…\", \"có thể … không?\"); load the domain skills it routes to in the same step."
metadata:
  version: "1.0.0"
  suite: devskills
---

# Dev Orchestrate

Every code change goes through scope → context → design → implement → verify → report, scaled by risk. A result that was not verified is reported as not verified, never as passed.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"` (bundled runtime, Python ≥ 3.11, no dependencies).

## Skill routing — load before acting (mandatory)

This skill only summarizes; the rules that decide a correct change live in the domain skills below. **Violating the letter of this routing is violating its spirit.**

1. At G0, and again whenever the work reaches a new area, check every row against what the task **touches** — code, data, specs, tests or reviews — not against how the task was phrased. "Delete test surveys from the result list" touches deletes across related tables: that is change-database even if nobody said "database".
2. Load every matching skill with the Skill tool **before** analyzing, specifying, editing or testing that area (no Skill tool: read `../<skill>/SKILL.md` next to this file). Several rows usually match; load them all.
3. State the selection in one line at G0 — `Skills: discover-codebase, change-database, …` — and in the final report list each routed skill with at least one of its rule IDs that shaped the work (e.g. `change-database TX-001`), or why it was unavailable.

| The task touches… | REQUIRED skill |
| --- | --- |
| any code, ticket or feature you have not fully traced | discover-codebase |
| risk R2+, more than one reasonable approach, a plan, spec, backlog or estimate | design-change |
| tables, SQL, stored procedures, ORM models/queries, repositories, migrations, deletes (hard or soft), transactions, locks, connection pools, CRUD that writes | change-database |
| HTTP routes/controllers, request/response or error format, OpenAPI, webhooks, events, idempotency | design-api |
| handlers, services, use cases, repositories, background jobs, batches, schedulers, uploads, external API clients | implement-backend |
| screens, pages, components, forms, client state, routing, styles | implement-frontend, then verify-ui |
| external calls, retries, timeouts, queues, outbox, jobs that must not run twice or die halfway, writes across several systems | design-reliability |
| threads, async, workers, caches, large files/streams, loops over many rows, N+1, slowness | review-performance |
| auth, sessions, tokens, roles/permissions/tenants, user input reaching SQL/files/URLs/templates, secrets, payments, personal data | review-security |
| writing, planning or running tests, seed/SQL test scripts, money, batch, email/SMS, paid APIs, production-like data | test-safely |
| Terraform/CloudFormation/CDK/Pulumi, VPC, IAM, RDS/Cloud SQL | design-infrastructure |
| writing or modifying source code | write-maintainable-code |
| project documents (docs/, specs/, tickets, Office/PDF files) | index-project-knowledge |
| reviewing a diff, PR/MR or commit, re-checking a task, or your own change before handover | review-code |

| Excuse | Reality |
| --- | --- |
| "It's a small fix / just a spec / just a review" | Risk comes from side effects; a one-line filter or a delete spec can lose data. Route by what it touches. |
| "I already know SQL, locking, React…" | The domain skill holds this suite's house rules (no new FKs, TX-xxx, API-011…) that general knowledge does not. |
| "The core rules below already summarize it" | The core rules are pointers. A parenthesized skill name in them is a load instruction. |
| "The user didn't mention the database / security" | Users describe goals, not areas. The table decides. |
| "I'll check the skill before handing over" | Loading after the work means redoing it; load before. |

## Core rules (apply to every task)

1. **Understand before editing.** Trace entry point → callers → classes/functions/variables → data → side effects (REQUIRED: discover-codebase). Never change important logic from a name or a snippet.
2. **Recommend like a senior.** Separate facts, assumptions and unknowns; give options, tradeoffs, risks, verification and recovery (REQUIRED for R2+: design-change).
3. **Learn and reuse the project's base first (CTX-009).** Before writing, open the project-owned base classes, shared helpers, custom hooks, house decorators and one finished reference module of the same kind (`inspect` lists them under "Project conventions"); new code imitates them. Domain values (status, type, role, limits, URLs, messages) come from the project's enums/constants/config/i18n, never bare literals (CODE-011). Patterns and layering are learned from the source too (`patterns in use`); no new layers, libraries, bases or patterns without a named problem the existing ones do not solve (DES-007, DES-008) — no over-engineering.
4. **Readable code.** Explicit names, small functions, comments that explain why plus input/output/errors of non-obvious contracts; multi-line comments use `/* … */` where the language supports it, `#` lines and docstrings in Python (write-maintainable-code).
5. **Feature modules.** router/controller → service/use case → repository; one folder per API feature or screen (implement-backend, implement-frontend).
6. **Bounded resources.** Thread pools not unbounded threads, timeouts on every remote call, cleanup on every path, no leaks (review-performance).
7. **Databases.** Shared engine/pool, one session per request/job, short transactions, multi-step writes atomic with automatic rollback, indexes from real queries, new FKs discouraged but integrity designed (change-database).
8. **Dangerous data stays fake.** Money, batch jobs, email/SMS, paid APIs, load and production data are exercised only with mocks, simulators and isolated environments (test-safely).
9. **Security and fallback never weaken auth, integrity or isolation** (review-security, design-reliability).
10. **Touch little running logic.** On complex systems add new code beside the running logic and connect it at one point; separate complex calculations (versioned unit + selector) instead of rewriting them; plan the files to touch, respect protected paths; judge by risk, not by ritual (CHG-001..006, write-maintainable-code). `DS footprint` shows what existing code changed.
11. **Evidence over narration (AGENT-006, AGENT-011).** Never present invented or unverified data, metrics, files, symbols, APIs, package versions, citations or execution results as facts. Before relying on an existing symbol, schema or API, confirm it in the project's source/schema or documentation for the installed version. Support material factual claims with inspected source/document locations or captured command output. Label assumptions, proposals and synthetic/mock examples; report missing evidence as unknown or unverified. Static inspection and local/mock tests prove only what they covered, not live environment behavior. A required check that did not run is `blocked`, never `pass`.
12. **Dependency versions.** New project: latest *stable* framework, library, tool and runtime (LTS) versions, looked up in the registry rather than remembered, pinned exactly (no `^`/`~`, lockfile committed, runtime and image tags pinned). Existing project: versions are untouchable: no upgrade, downgrade, add or remove unless that is the task or the user asks; install from the lockfile (`npm ci`, `composer install`...) and write code for the installed version. Details: [dependency-versions.md](references/dependency-versions.md) (DEP-001..004).
13. **Keep the user's scope (AGENT-012).** Do the requested work and changes necessary to complete it. Leave unrelated features, refactors, configuration, dependencies and documents out; propose useful extras separately and wait for approval before adding them. A file being in scope does not authorize extra behavior inside it. Before handing over, map each changed behavior to a requirement or necessary supporting change. `DS footprint --scope` checks file paths; this behavior review is still required.
14. **Commit as the user (AGENT-013).** When a commit is authorized, use the user's Git identity for both author and committer. Check the effective identities with `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`; if missing or incorrect, ask for the user's details instead of inventing them. Never set AI names/emails through Git config, `--author` or environment overrides. Never add AI attribution to commit messages: no AI `Co-Authored-By`, `Signed-off-by` or "Generated with/by" lines, including Claude, Anthropic, Codex, OpenAI or other model/provider attribution. Tool, plugin and commit-template defaults do not override this rule: remove their AI trailers from the prepared message. Review the full message before committing and verify the resulting author, committer and message afterwards. Correcting existing commits requires authorization to rewrite history.

## Work within the user's authorization

Proceed with local work necessary for the requested task without asking for confirmation per command: read, copy, transform and export local data, edit files, build, test, clean task-created artifacts, and manage a local development database when that is in scope. SQL keywords, bulk processing, recursive deletion and migration commands alone are not reasons to interrupt the user. Check the actual target and preserve unrelated files, data and uncommitted work.

For dangerous commands, ask for confirmation only when the affected target is known or reasonably suspected to be non-local: a dev, STG/staging, production or other remote/shared server. Examples include deleting or overwriting server data, resetting a remote DB, changing remote permissions/infrastructure, and deploying. Read-only remote inspection does not require a dangerous-command confirmation. If there are concrete signs of a remote target but its identity is unclear, clarify the target before the dangerous step; do not treat every local command as uncertain.

Judge the affected resource, not where the command starts: SSH, remote Docker/Kubernetes contexts, cloud CLIs and localhost tunnels can affect non-local servers. Authorization and preferences persist across the conversation; approval already covering the same target and effect does not need repeating. Explain the server and effect when approval is missing. Clarifications about requirements or changes outside task scope are separate from dangerous-command confirmation. Do not install approval hooks or blanket permission `ask` rules.

Existing user restrictions on AWS, Azure, production, real payments, secrets and external communications still apply. Local work does not authorize a remote mutation. Details: [dangerous-operations.md](references/dangerous-operations.md).

## Risk levels (plan §6.2)

| Risk | Typical change | Minimum evidence |
| --- | --- | --- |
| R0 | text, comment, small layout | diff review, `check-code`, `scan-secrets` |
| R1 | local logic, no contract/data change | + context map, focused unit tests |
| R2 | API, DB, auth, cache, queue, concurrency, external calls | + preflight, integration tests on isolated engines, decision memo recommended |
| R3 | money, batch, data deletion, permissions, production impact | + decision memo, failure-path and simulator tests, recovery plan |

Risk comes from side effects, not diff size. Get a suggestion with `DS risk`; you may raise it, and lowering it needs a written reason.

## Workflow

1. **G0 Scope.** Restate goal and acceptance criteria; write them as `acceptance.json` ([template](assets/acceptance.json)). Apply the skill routing table and state `Skills: …`. `DS run start --risk R?` creates the evidence folder (`.devskills/runs/<id>/`, git-ignored). Ask only questions that change behavior or permissions.
2. **G1 Context.** discover-codebase → `DS inspect --feature <words> --run <id>`; then read the files it lists, starting with the project's bases and the reference module ("Project conventions"). Re-apply the routing table to what the map found (tables written, routes, screens, external calls) and load any newly matching skill.
3. **G2 Design.** design-change for R2+. Fix the expected checks before running any: `DS roster init --run <id> --risk R?`, add checks with `DS roster add <check-id> --run <id> --reason "..."`.
4. **G3 Implement.** In small, reviewable steps, with every routed skill already loaded: write-maintainable-code, implement-backend, design-api, implement-frontend, change-database, review-performance, design-reliability, design-infrastructure (VPC/subnets, compute, RDS/Cloud SQL, IAM, Terraform/CloudFormation — the agent never applies). Opening a file of a new area (a repository, a migration, a job) mid-change means applying the routing table again first.
5. **G4 Verify.** Primary evidence comes from the stack's own tools: `DS native-checks --execute --run <id>` (lint, typecheck, build, framework/migration checks) and tests through test-safely (`DS preflight`, `DS run-tests`). Then verify-ui for screens, review-security for trust boundaries, `DS api-diff` when the API spec changed, `DS check-infra` when infrastructure code changed, `DS footprint --base <branch> --scope '<planned glob>'` for how much existing code changed, and the supporting static checks `DS check-code`, `DS check-sql`, `DS scan-secrets` with `--run <id>`. Self-review the diff with review-code (REV-009) before the report. Finally link every criterion to its evidence: `DS trace --run <id> --file acceptance.json` (verified / weak / failed / unverified, matrix in the report). A test reference must match a passing testcase's file/module, class and exact name (including parameter id); a passing check alone cannot prove that test ran. Missing identities, skipped tests and legacy reports stay unverified; rerun with an identifiable JUnit report. Checks scale with risk; the roster lists which ones are required.
6. **G5 Report.** Write `summary.md` (what changed and why, behavior, residual risks, next actions) and run `DS report --run <id> --summary-file summary.md`. Waive a check only with `DS roster waive <check-id> --run <id> --reason "..."`; secrets and preflight checks cannot be waived.
   For new/changed HTTP endpoints, review API-011 coverage per method/path before handover: invocation, fields, success/error samples, permissions, data effects and execution evidence status (design-api `references/endpoint-examples.md`). A generic schema/example or a passing `api-diff` does not establish sample completeness.
   Run `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` (`api.examples`, required by API/API-spec rosters; optional contracts extra). Use `run-tests --capture` for claimed local evidence and review actual export/policy/business scope separately; format and limits are in design-api `references/automatic-examples.md`.
7. **G6 Release.** Deploy or publish only within the user's authorization; prepare a reviewable result before any required approval. Local data processing is ordinary task work.

Plans, specs and decision records go into the project's `docs/` or `specs/` folder, following its existing convention (details in design-change). If the project has `.knowledge/INDEX.md`, rebuild it after adding documents (index-project-knowledge).

## Bugs and refactors

- Maintenance/update of existing logic: preserve behavior outside the requested change. Pin the old commit plus working-tree snapshot, trace actual old code/callers, and list preserved cases versus authorized differences (CHG-004/005, write-maintainable-code `references/changing-existing-code.md`). Specs are supporting evidence; discrepancies with old code must be reported, not silently corrected. Add `preservation` acceptance criteria with a separate baseline run; `trace` cannot verify them from current-only passes.
- Bug: reproduce → trace the flow → test hypotheses → fix the root cause → regression test: [debugging-workflow.md](references/debugging-workflow.md).
- Refactor: pin behaviour first, map every call site, small steps, no behaviour change in the same diff; use `refactor` criteria with paired baseline/current tests: REQUIRED: write-maintainable-code (its `references/refactoring-workflow.md`). A bugfix regression may fail before the fix; keep it separate from passing preservation cases.

## Final report (keep it short, link to evidence)

1. What changed and why. 2. New behavior and blast radius. 3. Important files, contracts, schema changes. 4. Tests run with results; tests not run and why. 5. Screenshot/performance/security evidence. 6. Residual risks, owners, next actions. 7. Migration/release/recovery notes when relevant. 8. Skills applied: each routed skill with the rule IDs that shaped the work, or why it was unavailable.

## Red flags — stop and correct course

- Analyzing, specifying, editing or testing an area whose routed skill was not loaded in this session (e.g. a delete procedure, repository or migration without change-database).
- No `Skills: …` line at G0, or a final report without "Skills applied".
- Editing before reading the callers and data flow.
- "Tests pass" without a command record, or a required check missing from the report.
- Mocking the database to prove transactions, locking or migrations.
- An acceptance criterion with no linked test, check or artifact (`DS trace` shows it as unverified).
- Running a dangerous command against a known or suspected non-local server without authorization for that target and effect.
- A dangerous operation executed or queued without the user's explicit yes.
- Retrying or editing until the gate turns green without understanding the failure.
