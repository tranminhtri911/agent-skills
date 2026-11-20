# Sub tasks: how small, and what each file contains (SPEC-004)

## How to split

- One sub task = one reviewable change with its own test: about 0.5–4 hours. Bigger → split again.
- Split along the flow and the layers: data (migration, model, query) → domain logic (calculation, rule, state transition) → API/controller → screen → outputs (PDF, CSV, mail, calendar) → jobs → tests and evidence.
- Keep shared groundwork first (types, constants, helpers), then each behaviour, then integration, then E2E and evidence.
- Each sub task names what it depends on (`depends_on`); no cycles.
- A sub task never mixes a refactor with a behaviour change (CODE-009).
- Work already on the branch keeps its sub task with `"status": "done"` in the plan and "Đã triển khai trong <commit>" in its Overview; the estimate page shows total and remaining hours.
- Write each section as short lists: one fact per line (lines over 200 characters fail the build).

## File: `sub_tasks/taskNN_<slug>.md`

`DS spec build` requires these `##` sections (English or Vietnamese headings): **Overview**, **Implementation**, **Unit test**, **E2E test**, **Verify**. Add **Files** and **Done criteria** when useful. Example: [subtask.example.md](../assets/subtask.example.md).

```markdown
# task02: <title>

- Estimate: 2h · Depends on: task01 · Plan: ../plan.html (Changes → <item>)

## Overview
What this task changes and what it must not change.

## Implementation
1. `path/to/file.ext`: exact change (function, signature, query, component).
2. …
Files: list of files created / changed.

## Unit test
Test file and cases with inputs and expected values; failure paths.

## E2E test
Checklist case ids and steps this task makes pass (TC01 step 4-6), or why none.

## Verify
How to see it work locally: data, screen/API, exact expected values.

## Done criteria
Tests that pass, checklist cases OK, reviewer check.
```
