---
name: dev-orchestrate
description: "Use when working on any development task or ticket for an application (backend, frontend, API, database, jobs, infrastructure), in any language — requirements, impact or feasibility, planning or specifying, implementing a feature, bugfix or refactor, tests, review, commit or reporting results. Triggers (vi): làm task, ticket, thêm chức năng, sửa lỗi, triển khai, phân tích tác động, viết spec, test, review, commit, báo cáo kết quả. Repository-specific questions are in scope; pure conceptual questions do not require the implementation workflow. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.3"
  suite: devskills
---

# Dev Orchestrate

Every code change goes through scope → context → design → implement → verify → report, scaled by risk. A result that was not verified is reported as not verified, never as passed.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"` (bundled runtime, Python ≥ 3.11, no dependencies).

## Skill routing — scoped loading (ROUTE-001)

For repository development, load this router first. Select domain skills from the actual changed behavior, commands and risk, not keywords alone. Load the owning skill before working in its area, once per session; load deeper references only when needed. A mention of a database in a typo fix does not make it a database change. Queries, locks, migrations, payments, permissions and external effects always require their safety skills regardless of diff size.

- Unfamiliar code → discover-codebase; design choices or R2+ → design-change.
- SQL/ORM/data integrity → change-database; endpoint contracts → design-api.
- Server logic → implement-backend.
- UI development and maintenance → `implement-frontend`. Start with the project's comparable screens and design patterns (CTX-009). Load the available `ui-ux-pro-max` for design decisions only where the project lacks a suitable pattern (FE-014).
- Rendered UI verification, UX review, responsive defect diagnosis and every UI E2E run → `verify-ui` and `ui-ux-pro-max`, including review-only requests (FE-010, FE-014). Visible changes receive this verification before handover. If `ui-ux-pro-max` is unavailable, record that and use the local visual checklist. Load `implement-frontend` when the task includes a fix or implementation.
- Remote calls/retries/jobs → design-reliability; concurrency/resource use → review-performance.
- Trust boundaries/secrets/permissions → review-security; tests → test-safely.
- Infrastructure → design-infrastructure; source edits → write-maintainable-code and code-style.
- Project document search/updates → index-project-knowledge; diff review → review-code.

Small conceptual questions without repository work receive a direct answer, without a development run. State selected skills briefly and finish repository work with `Skills applied` and applicable rule IDs. A project can document narrower routing for unrelated areas; it cannot waive safety for actual cloud, remote DB, money or permission operations.

## Execution modes (MODE-001)

| Mode | Selection | Required work |
| --- | --- | --- |
| Lightweight | R0 or bounded R1, no trust/data/contract effects | Read affected context, focused check or test, review diff, concise result; no run directory, roster, trace or generated report required |
| Standard | R1 spanning modules or requiring reproducible evidence | Context map, focused tests and stack checks, concise evidence; use run/trace when useful |
| Strict | R2/R3, API/data/auth/payment/concurrency/providers | Full evidence workflow in [execution-workflow.md](references/execution-workflow.md), applicable safety checks, failure paths and recovery |

`DS risk` suggests the mode; confirm actual effects. No mode bypasses OPS-011/012/013, truthful evidence or scope protection. Do not lower risk because a diff is short.

## Core rules (apply to every task)

1. **Understand before editing.** Trace entry point → callers → classes/functions/variables → data → side effects (REQUIRED: discover-codebase). Never change important logic from a name or a snippet.
2. **Recommend like a senior.** Separate facts, assumptions and unknowns; give options, tradeoffs, risks, verification and recovery (REQUIRED for R2+: design-change).
3. **Learn and reuse the project's base first (CTX-009).** Before writing, open the project-owned base classes, shared helpers, custom hooks, house decorators and one finished reference module of the same kind (`inspect` lists them under "Project conventions"); new code imitates them. Domain values (status, type, role, limits, URLs, messages) come from the project's enums/constants/config/i18n, never bare literals (CODE-011). Patterns and layering are learned from the source too (`patterns in use`); no new layers, libraries, bases or patterns without a named problem the existing ones do not solve (DES-007, DES-008) — no over-engineering.
4. **Readable code.** Explicit names, small functions, comments that explain why plus input/output/errors of non-obvious contracts; comments follow the repository and language conventions (write-maintainable-code); naming, layout and pattern choice follow the language and framework (code-style).
5. **Existing architecture first.** Follow the repository’s layers and module layout; introduce a service/repository or feature folder only for a concrete responsibility (implement-backend, implement-frontend).
6. **Bounded resources.** Thread pools not unbounded threads, timeouts on every remote call, cleanup on every path, no leaks (review-performance).
7. **Databases.** Shared engine/pool, one session per request/job, short transactions, multi-step writes atomic with automatic rollback, indexes from real queries, FK policy follows project conventions with integrity designed explicitly (change-database).
8. **Dangerous data stays fake.** Money, batch jobs, email/SMS, paid APIs, load and production data are exercised only with mocks, simulators and isolated environments (test-safely).
9. **Security and fallback never weaken auth, integrity or isolation** (review-security, design-reliability).
10. **Touch little running logic.** On complex systems add new code beside the running logic and connect it at one point; separate complex calculations (versioned unit + selector) instead of rewriting them; plan the files to touch, respect protected paths; judge by risk, not by ritual (CHG-001..006, write-maintainable-code). `DS footprint` shows what existing code changed.
11. **Evidence over narration (AGENT-006, AGENT-011).** Never present invented or unverified data, metrics, files, symbols, APIs, package versions, citations or execution results as facts. Before relying on an existing symbol, schema or API, confirm it in the project's source/schema or documentation for the installed version. Support material factual claims with inspected source/document locations or captured command output. Label assumptions, proposals and synthetic/mock examples; report missing evidence as unknown or unverified. Static inspection and local/mock tests prove only what they covered, not live environment behavior. A required check that did not run is `blocked`, never `pass`.
12. **Dependency versions.** New project: latest *stable* framework, library, tool and runtime (LTS) versions, looked up in the registry rather than remembered, pinned exactly (no `^`/`~`, lockfile committed, runtime and image tags pinned). Existing project: versions are untouchable: no upgrade, downgrade, add or remove unless that is the task or the user asks; install from the lockfile (`npm ci`, `composer install`...) and write code for the installed version. Details: [dependency-versions.md](references/dependency-versions.md) (DEP-001..004).
13. **Keep the user's scope (AGENT-012).** Do the requested work and changes necessary to complete it. Leave unrelated features, refactors, configuration, dependencies and documents out; propose useful extras separately and wait for approval before adding them. A file being in scope does not authorize extra behavior inside it. Before handing over, map each changed behavior to a requirement or necessary supporting change. `DS footprint --scope` checks file paths; this behavior review is still required.
14. **Commit as the user (AGENT-013).** When a commit is authorized, use the user's Git identity for both author and committer. Check the effective identities with `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`; if missing or incorrect, ask for the user's details instead of inventing them. Never set AI names/emails through Git config, `--author` or environment overrides. Never add AI attribution to commit messages: no AI `Co-Authored-By`, `Signed-off-by` or "Generated with/by" lines, including Claude, Anthropic, Codex, OpenAI or other model/provider attribution. Tool, plugin and commit-template defaults do not override this rule: remove their AI trailers from the prepared message. Review the full message before committing and verify the resulting author, committer and message afterwards. Correcting existing commits requires authorization to rewrite history.

## Work within the user's authorization

Proceed with local work necessary for the requested task without asking for confirmation per command: read, copy, transform and export local data, edit files, build, test, clean task-created artifacts, and manage a local development database when that is in scope. SQL keywords, bulk processing, recursive deletion and migration commands alone are not reasons to interrupt the user. Check the actual target and preserve unrelated files, data and uncommitted work.

**Cloud access requires explicit approval (OPS-011), including reads.** Never independently connect to cloud or use any cloud profile, secret key, access key, token, service account, SSO session or ambient credentials. Before each cloud command/tool action, or an explicitly listed batch, warn with the exact actions, account/profile, environment, target and risks/costs, then wait for the user's explicit approval covering those actions. This applies to CLI, SDK, scripts, Terraform and MCP on every environment, including dev/STG/production; list/get/describe, identity checks, login, connection tests and remote plans/dry runs are included. Existing credentials, a read-only label and a general request to inspect/test do not authorize cloud access. Do not make a cloud call to identify the account before approval; report unknown details and clarify them without exposing credentials. Only genuinely offline work and credential-free local mocks avoid this cloud approval requirement.

**Every non-local database operation requires explicit approval (OPS-012).** Never independently connect to or do anything on a database outside this machine, whether cloud or non-cloud, dev/STG/production or another remote/shared environment. Before each action or explicitly listed batch, warn with exact commands/queries, server/environment, database, purpose and risks, then wait for explicit approval covering those actions and targets. This includes SELECT, schema/metadata inspection, estimated/actual EXPLAIN, health/connection checks, exports/backups, writes, migrations, restores and maintenance, including indirect access through ORM/SDK, apps/scripts/tests, SSH/tunnels, remote Docker/Kubernetes contexts and MCP. Existing credentials, sessions and localhost tunnels do not grant permission. Do not connect to identify/validate an unknown target before approval; a general request to inspect/debug/test is not approval. Only in-scope work on confirmed local databases and offline review may proceed directly.

For remote operations outside cloud and database access, ask for confirmation when a dangerous command affects a known or reasonably suspected non-local server: dev, STG/staging, production or other remote/shared infrastructure. Examples include deleting or overwriting server data, changing remote permissions/infrastructure, and deploying. Read-only inspection outside cloud and database access does not require this dangerous-command confirmation. If concrete signs suggest a remote target but its identity is unclear, clarify it before the dangerous step; do not treat every local command as uncertain.

Judge the affected resource, not where the command starts: SSH, remote Docker/Kubernetes contexts, cloud CLIs and localhost tunnels can affect non-local servers. Classify targets as proven local, non-local or unknown (OPS-014): indirect commands, env/config targets, network mounts and tunnelled localhost ports are not proof of local; unresolved means non-local, and a timeout never approves it. Authorization and preferences persist across the conversation; do not repeat approval already covering the exact cloud/non-local DB actions or, for other remote work, the same target and effect. New cloud/non-local DB actions, changed targets/profiles and retries outside the approved scope require a new warning and approval. Explain the server and effect when approval is missing. Clarifications about requirements or changes outside task scope are separate from dangerous-command confirmation. Do not install approval hooks or blanket permission `ask` rules.

Existing user restrictions on AWS, Azure, production, real payments, secrets and external communications still apply. Local work does not authorize a remote mutation. Details: [dangerous-operations.md](references/dangerous-operations.md).

**Use an interactive approval dialog (OPS-013) when approval is missing.** Use a supported confirmation tool, such as `request_user_input_async` on the current Codex surface, with a short icon/action/environment title (`🗄️ Đọc DB · STG`, `☁️ Xem AWS · DEV`), exact operation/target details and refusal/scoped-approval choices. Refusal goes first when the first choice is preselected. A default selection, tool return, dismissal or silence is not consent; await the actual explicit answer before execution. Do not change host permissions to force a native popup. If no suitable tool is available, state that limitation and wait for consent in chat. Read [approval-dialog.md](references/approval-dialog.md) for the tool payload, pending/denied behavior and preview limits.

## Risk levels (plan §6.2)

| Risk | Typical change | Minimum evidence |
| --- | --- | --- |
| R0 | text, comment, small layout | diff review and a relevant focused check |
| R1 | local logic, no contract/data change | + context map, focused unit tests |
| R2 | API, DB, auth, cache, queue, concurrency, external calls | + preflight, integration tests on isolated engines, decision memo recommended |
| R3 | money, batch, data deletion, permissions, production impact | + decision memo, failure-path and simulator tests, recovery plan |

Risk comes from side effects, not diff size. Get a suggestion with `DS risk`; you may raise it, and lowering it needs a written reason.

## Bugs and refactors

- For analysis, features, fixes and refactors that affect business behavior, load test-safely during scoping. Apply TEST-013 before proposing or editing the behavior and recheck the scenarios before closing. Analysis-only work may leave scenarios unexecuted. Label source inferences and runtime results separately, and run focused safe probes when needed to support material claims.

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
- Any cloud connection or credential use without a warning and explicit approval for the exact actions (OPS-011), including read-only inspection and identity/connection checks.
- Any non-local database connection or operation without a warning and explicit approval for the exact actions (OPS-012), including SELECT, schema/plan inspection, health checks and backups through existing sessions or tunnels.
- Retrying or editing until the gate turns green without understanding the failure.
