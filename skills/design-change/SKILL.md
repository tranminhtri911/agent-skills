---
name: design-change
description: "Use when evaluating approaches, feasibility, impact, tradeoffs, rollout or risks for a repository change, including cross-system changes. Triggers (vi): đề xuất giải pháp, khả thi, phân tích tác động, lên kế hoạch, ước lượng, kiến trúc."
metadata:
  version: "1.0.7"
  suite: devskills
---

# Design Change

Recommend like a senior engineer: the simplest design that satisfies the requirement, with explicit tradeoffs, failure modes, verification and recovery. Decide before coding; record decisions where the team can find them.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — the domain skills judge each option

A plan or spec is only as good as the domain rules it was checked against. Before writing options, load (Skill tool) the domain skill of every area the change touches, using dev-orchestrate's routing table: tables, deletes, transactions or locks → change-database; endpoints → design-api; jobs, retries, external systems → design-reliability; auth, tenants, personal data → review-security; load, batches, caching → review-performance; test plan → test-safely; screens → implement-frontend. Cite their rule IDs in the memo where they decide an option.

## When to write what

| Situation | Artifact |
| --- | --- |
| R0-R1 bugfix | 3-5 lines in the task reply: cause, fix, test |
| R2 change | Mini memo: sections 1, 3, 4, 6, 7 of the template |
| R3, or hard to reverse, or spans modules | Full decision memo ([template](assets/decision-memo.md)); ADR if it sets a lasting convention |
| User asks for a plan/spec | Plan or spec document in the project's docs folder; a ticket's plan with sub tasks and test checklist → task-spec (`specs/<task>/`) |

## Where documents live

Follow the project's existing convention (look for `docs/`, `specs/`, `docs/specs/`, `docs/plans/`, `docs/adr/`, `ticket/<id>/`). Without one, use:

- Plans: `docs/plans/YYYY-MM-DD-<topic>.md`
- Specs: `docs/specs/<feature>.md` (behavior, contracts, acceptance criteria)
- Decisions: `docs/adr/NNNN-<decision>.md`

Never leave plans only in chat or in random root files. After adding documents, rebuild the knowledge index if the project has one (`python3 .knowledge/build.py`). Record the memo as run evidence: `DS attest --run <id> --check-id design.memo --file docs/plans/<file>.md`.

## Decision memo checklist (plan §8.1)

When the context map shows `code_graph.available`, take the blast radius for the memo from `codegraph impact <Symbol> --depth 2 --json` (read-only) instead of estimating it.

1. Problem and done criteria. 2. Current state with evidence; unknowns that matter. 3. Proposed option and meaningful alternatives. 4. Tradeoffs: complexity, correctness, maintainability, performance, operations, cost, migration. 5. API/data contract changes and backward compatibility. 6. Failure modes, partial completion, concurrency, recovery. 7. Test matrix and evidence to collect. 8. Rollout order, rollback/roll-forward, stop conditions.

## Rules

- DES-001: label requirement vs assumption vs proposal; never turn your preference into a business requirement.
- DES-002: prefer the simplest change; add extension points only with a concrete reason.
- DES-003: for ambiguous money, permission or deletion semantics, ask one narrow question; continue the analysis that is not blocked.
- DES-005: measure before adding cache, queues or concurrency; state performance targets separately from guesses.
- DES-006: define "stop if not met" criteria for migrations, batches and releases.
- Prefer the repo's framework facilities (transactions, validation, queues) over new libraries.
- DES-007: learn the patterns the source already uses before proposing one (`inspect` → patterns in use); a new pattern, layer or architecture style must name the concrete problem in this change it solves and why the existing ones do not; otherwise use the existing one. A new architecture for the whole project is its own proposal, never part of a feature.
- For changes to complex running logic, the memo states the footprint: files touched and why, in-place vs separate unit + seam, how the old path is pinned and compared (write-maintainable-code `changing-existing-code.md`).
- DES-008: a new dependency states why the framework/stdlib/existing packages do not cover it, license, maintenance, weight and audit result (write-maintainable-code `patterns-and-architecture.md`).

## Senior heuristics

- Duplicate submit: disabling the button is UX only; the server needs idempotency plus a unique constraint.
- Slow query: query shape, index and pagination before a distributed cache.
- Multi-system steps: DB transaction + outbox + idempotent consumer + reconciliation, not a "distributed rollback".
- New FK: follow project policy and existing migrations; prefer enforced integrity unless there is a documented reason otherwise (change-database).
- Modular monolith first; split services only for real ownership/scaling boundaries.

## Red flags

Options without tradeoffs · a pattern or layer with no named problem ("for flexibility", "best practice") · "it should be fine" without a test · rollback plan "revert the code" for a data migration · a design that needs production access to verify.
