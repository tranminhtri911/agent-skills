---
name: task-spec
description: "Use when producing a written ticket spec or task plan with plan.html, subtasks and a test checklist. Triggers (vi): viết spec, lên plan cho ticket, chia task, estimate task, require.md, plan.html."
metadata:
  version: "1.0.8"
  suite: devskills
---

# Task Spec

One folder per task turns a raw requirement into a plan people can review and work from: the plan explains what changes and why, with flow diagrams; the sub tasks are small enough to do and test one by one; the checklist says how to prove the result. Every statement comes from the requirement or from code you read; guesses are labelled.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before writing that part; dev-orchestrate routes the whole task.

- Reading the code the task touches (current flow, callers, data) → **REQUIRED:** discover-codebase.
- Options, tradeoffs, risks and rollout → **REQUIRED:** design-change; and the domain skill of every area the plan changes (change-database, design-api, implement-backend, implement-frontend, design-reliability, review-security, review-performance).
- Test plan and checklist cases → **REQUIRED:** test-safely. Use the checklist produced by `DS spec build`; apply e2e-evidence when executing or reporting the cases.

## Folder layout (SPEC-001)

```
specs/                           project's specs root: specs/, docs/specs/ or .devskills.toml [spec].root
  <task>/                        one folder per ticket or task, e.g. no63_5
    require.md                   the requirement, verbatim, plus one "Nguồn:" line — nothing else
    plan.html                    the plan (DS spec build): one block per page, small collapsible items, diagrams
    sub_tasks/
      task01_<slug>.md           one small task: overview, implementation, unit test, E2E test, verify
    checklist.html               test cases (DS spec build), the page e2e-evidence uses
```

No JSON file stays in the folder. Write the plan and checklist JSON in a scratch file outside it; each page embeds its data, and `DS spec source --task <task> --part plan|checklist --out <file>` gives it back for the next edit.

## Procedure

1. **Folder and requirement.** Task id from the prompt, else the branch (`fix/no63_5` → `no63_5`). `DS spec init --task <task>` creates the folder, `sub_tasks/` and a short `require.md` (never overwrites). Paste the requirement into `require.md` exactly as given — no translation, summary or analysis — and fill `Nguồn:` (who, when, ticket). No requirement → ask for it.
2. **Read before planning (SPEC-002).** Read `require.md`, the project's instructions and documents, and the code along the flow the requirement touches (discover-codebase): entry points, callers, data, jobs, outputs (PDF, CSV, mail, calendar). If the branch already has an implementation, read its diff against the base: the current flow is the base, the target flow is the branch.
3. **Write the plan (SPEC-003).** All standard blocks: overview, current_flow, target_flow, changes, impact, verify, test, risks, confirm, estimate, deploy (`not_applicable` with the reason when one does not apply). Format, block contents and diagram schema: [plan-format.md](references/plan-format.md).
4. **Diagrams (SPEC-008).** current_flow and target_flow each carry a diagram `{nodes, edges}`: every step, decision, data store and external system on the path, in order; the target diagram marks nodes `new`, `changed` or `removed`. Add diagrams wherever a branch or a sequence is easier to see than to read.
5. **Small, explicit items (SPEC-009).** One item per point; one fact per line; lists and tables instead of paragraphs; child items (`items`) for detail. `DS spec build` fails on a line over 200 characters or a table cell over 140, and warns on an item over 18 lines.
6. **Sub tasks (SPEC-004).** As small as can be done, reviewed and tested alone (about 0.5–4 h), ordered by `depends_on`, `status: done` for work already on the branch. Each `sub_tasks/taskNN_<slug>.md` has `## Overview`, `## Implementation`, `## Unit test`, `## E2E test`, `## Verify` (and Files, Done criteria), written as short lists. Template: [subtasks.md](references/subtasks.md).
7. **Checklist (SPEC-005).** Every case the change needs (main path, each rule branch, switching back and forth, create and edit, untouched data, every output, errors), concrete data and exact expected results in vi/en/ja: the e2e-evidence checklist schema, ids `<task>-TC01`. Reuse an existing checklist of the task as it is when one exists.
8. **Build (SPEC-006).** `DS spec build --task <task> --plan <scratch>/plan.json --checklist <scratch>/checklist.json` validates everything and writes `plan.html` and `checklist.html`. Fix every finding and build again until the gate passes. Later edits: `DS spec source … --out <scratch>/plan.json`, edit, build again.
9. **Report to the user:** the plan path, open questions (they block the decisions they name), total and remaining estimate, assumptions to confirm, and what you could not verify in the code. Do not implement unless the user asks.

## Rules (SPEC-001…SPEC-009)

- SPEC-001 one folder per task; `require.md` holds only the verbatim requirement and its source; no JSON next to the pages.
- SPEC-002 the plan cites what it is based on: requirement lines, file paths and functions read; current flow from the code, never from memory.
- SPEC-003 all standard blocks are present; "not applicable" carries its reason; requirement, assumption and proposal are labelled (DES-001).
- SPEC-004 sub tasks are small, ordered, estimated in hours, marked done when already implemented, and each says how it is implemented, unit-tested, E2E-tested and verified.
- SPEC-005 the checklist covers every behaviour the plan changes or must keep, with exact expected values, in vi/en/ja.
- SPEC-006 `plan.html` and `checklist.html` come from `DS spec build`, never by hand; rebuild after every change.
- SPEC-007 unclear money, permission, deletion or data semantics become `confirm` items with an owner; the plan continues with the parts not blocked (DES-003).
- SPEC-008 both flows have a diagram; the target diagram marks what is new, changed or removed.
- SPEC-009 one fact per line, small items, child items for detail; no long paragraphs or one-line walls of text.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Analysis or a translation added to require.md | require.md = the requirement as received + `Nguồn:`; the rest goes in the plan |
| "Current flow" as a paragraph | Diagram from the code + a short list of the functions on the path |
| One item with ten sentences | Split into child items, one point each |
| plan.json / checklist.json left in the folder | Keep JSON in a scratch file; `spec source` restores it |
| One sub task "implement feature" of 3 days | Split by layer and behaviour until each fits 0.5–4 h with its own test |
| Questions hidden in the text | One `confirm` item each, with status and owner |
| plan.html edited by hand | Edit the JSON, run `DS spec build` |
