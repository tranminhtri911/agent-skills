---
name: e2e-evidence
description: "Use when running or verifying E2E tests or a manual test checklist for a ticket or task: creating the checklist (checklist.html) from the branch or prompt, capturing a screenshot per step, verifying screenshots against expected results, writing per-case OK/NG summaries and the evidence report. Triggers (vi): chạy test e2e, verify e2e, test theo checklist, tạo checklist, evidence, chụp ảnh từng step, đánh giá OK/NG, báo cáo test. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.5"
  suite: devskills
---

# E2E Evidence

Every E2E or manual test run of a task leaves the same evidence: a checklist with concrete steps, data and expected results; one folder per case with a screenshot per step; a summary per case that says OK or NG from what the screenshots actually show; and a report over everything. Nothing is OK until a screenshot proves it.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Test environment, test data, profiles and anything with money, email, calendars or external providers → **REQUIRED:** test-safely.
- Reading screens for layout or UX problems while capturing → verify-ui.
- Cases that read or write a database, or a target that may be a shared server → change-database and dev-orchestrate's authorization rules (OPS-011..014).

## Folder layout (E2E-001)

```
<evidence root>/                 gitignored; `deploy/evidence`, `evidence`, ... or .devskills.toml [evidence].root
  <task>/                        one folder per ticket or task, e.g. no63_5
    checklist.json               the cases (source of truth; stays with its run when the folder is moved)
    checklist.html               rendered checklist for manual ticking (DS evidence checklist)
    <case-id>_<slug>/            one folder per case, e.g. no63_5-TC01_main-case-allday-qty5
      step01_<what-is-shown>.png
      step02a_<...>.png  step02b_<...>.png
      summary_<case-id>.md       result: OK | NG | PARTIAL | BLOCKED | NOT_RUN + step table
    report.html                  the one report (DS evidence report): every case OK/NG with reason and links,
                                 then each case's steps with result, observation and screenshots
```

## Procedure

1. **Task and root.** Task id from the prompt, else the branch (`fix/no63_5` → `no63_5`). `DS evidence init --task <task>` creates `<root>/<task>/` and adds the evidence root to `.gitignore` (screenshots can show personal data; evidence is never committed).
2. **Checklist (E2E-002).** If `<task>/checklist.json` exists, use it; if the task has a spec (`specs/<task>/checklist.html`, task-spec), take its cases: `DS spec source --task <task> --part checklist --out <root>/<task>/checklist.json`. Otherwise build every case for the task — from the prompt, the branch diff against its base, the ticket/spec documents, existing tests and any older checklist of the task (convert it; keep the original). Each case: id with the task prefix (`<task>-TC01`), title, purpose, preconditions, concrete test data, numbered steps with action, data and exact expected results (screen text, amounts computed by hand), all in Vietnamese, English and Japanese. Coverage, schema and how to derive cases: [checklist-format.md](references/checklist-format.md). Then `DS evidence checklist --task <task>`: it validates, writes `checklist.html` (left menu, language switch, collapsible cases with checkboxes, pages with totals) and creates the case folders. When the user only asked for the checklist, stop here and show it.
3. **Environment (E2E-003).** Classify the target before the first click (OPS-014). Prefer a local, disposable environment with synthetic data. Staging, production-like, shared servers and any app whose database or calendar/email/payment integrations are real need the user's explicit approval for the exact cases, data they create or change and cleanup (OPS-013 dialog); production never. A container on this machine can still be the shared server: check what its database and domain serve. Logins come from the user or test fixtures, never from reading `.env` or credential files. [run-and-capture.md](references/run-and-capture.md).
4. **Run and capture (E2E-004).** Run the project's E2E suite when it exists (through test-safely), otherwise drive the browser step by step, or take the user's screenshots for a manual run. Save at least one screenshot per step that has an expected result, straight into the case folder, named `stepNN[a-z]_<what-is-shown>.png`; preconditions are `step00[a-z]_...`, extra proof is `extra_...`, one screenshot proving two steps is `step02-03_...`. Keep the value being checked inside the frame.
5. **Verify each screenshot (E2E-005).** Open every image and compare what it shows with the expected result of its step: exact text, every amount (recompute independently), state and URL. Rename images that do not match their step yet. Record a step as passed only from a screenshot you looked at; no screenshot means no evidence, never a pass. A screen that differs from the expected result is NG even when the app did not error.
6. **Summary per case (E2E-006).** Write `summary_<case-id>.md`: front matter (`case`, `result`, `reason` for anything not OK, `steps_passed`, `steps_total`, `environment`, `tested_at`, `tester`), a `## Steps` table with exactly the columns `Step | Checklist action | Image | What the image shows | Result` (one row per step, the step number in the first column — the report reads it), then `## Cross-check`, `## Notes` and `## Conclusion`. Write each observation as the exact screen values, one fact per line or separated by ` / `. Template and result rules: [verify-and-summarize.md](references/verify-and-summarize.md).
7. **Report (E2E-007).** `DS evidence report --task <task>` writes the task's only report, `<task>/report.html`: verdict and counts, a table of every case grouped NG → BLOCKED → PARTIAL → NOT RUN → OK with its reason and links to its block, folder and summary, then per case its checklist steps, each with the ticked/unticked result, expected and observed values and its own screenshots. Folders that are not cases of the checklist are listed separately and not counted. Gate: any NG fails; NOT_RUN/BLOCKED or a missing summary blocks; PARTIAL warns; all OK passes. Fix naming and missing-image findings before handing over. Keep `checklist.json` inside the task folder, also when copying or moving a run.
8. **Tell the user** the verdict per case (OK/NG/PARTIAL/BLOCKED) with the reason, the NG details (expected vs observed, screenshot), what was not run and why, data created or changed on any shared environment, and the report path.

## Rules (E2E-001…E2E-010)

- E2E-001 one folder per task under one gitignored evidence root; one folder per case named `<case-id>_<slug>`; nothing from it is committed or uploaded.
- E2E-002 a checklist exists before the run; cases carry the task prefix, concrete data and exact expected results in vi/en/ja; it is generated from evidence (diff, specs, tests), and assumptions are marked.
- E2E-003 no clicks on a non-local or unknown target without approval for those cases and their data effects; never production; no real payments, real recipients or real calendars without explicit approval.
- E2E-004 a screenshot per step with an expected result, named by step after it was checked.
- E2E-005 judge from the screenshot, not from the action having succeeded; recompute numbers yourself.
- E2E-006 results are OK, NG, PARTIAL, BLOCKED or NOT_RUN — no other word, no OK with a missing screenshot.
- E2E-007 the report is generated by `DS evidence report`, never written by hand, and reruns after every change of a case folder.
- E2E-008 a failed case gets a reproduction (steps, data, expected vs observed) before any fix; a fix is a separate task with its own checklist run.
- E2E-009 deviations from the checklist (another record used, a step skipped, different data) are written in the summary and lower the result to PARTIAL unless the purpose is still fully proven.
- E2E-010 do not change application code, tests or the checklist's expected results to make a case pass.

Learned from a real run (folder names, screenshot names, summary wording): [worked-example.md](references/worked-example.md).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| "PASS" because the save button worked | Open the saved record and compare the values with the expected result |
| Screenshot cuts off the line being checked | Scroll or capture the element; take `step02b` |
| `Screenshot 2026-11-18 at 16.37.12.png` in the folder | Rename to `stepNN_<what-is-shown>.png` after checking which step it proves |
| Testing on staging without asking because it is "only a test" | Approval for the cases and the data they change (E2E-003) |
| Checklist in one language only | vi / en / ja for every title, step and expected result |
| Report hand-written in HTML | `DS evidence report` |
