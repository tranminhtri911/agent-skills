# Verify screenshots and write the case summary (E2E-005, E2E-006)

## Verify

For every step of the case, in order:

1. Open the screenshot(s) of the step and read what they show: URL, screen title, the fields and values under test, messages. Each value the step names carries a red frame with a numbered tag; a missing, misplaced or covering frame means a retake, not a pass. The frame shows where to look — read the value itself, never the tag.
2. Compare with the step's expected result word for word and number for number. Recompute every amount from the inputs (tax, rounding, tiers) instead of trusting either the screen or the checklist.
3. Check the same value across every place it appears (form/memo, detail screen, PDF, calendar, CSV): they must agree.
4. Decide the step: `PASS` (shown and matches), `NG` (shown and differs — write expected vs observed), `NO EVIDENCE` (no screenshot shows it), `NOT RUN`.
5. If an image belongs to another step than its name says, rename it now and update references.

Never infer a value that is outside the frame. "The toast said saved" proves the save, not the saved values.

## Case result

| Result | When |
| --- | --- |
| `OK` | Every step with an expected result is PASS with a screenshot, and the case purpose is proven as written |
| `NG` | At least one step shows a different result than expected (a product defect or a wrong expectation to raise) |
| `PARTIAL` | No NG, but a step has no evidence, or the run deviated from the checklist (other record, other data, step merged) so the purpose is only partly proven |
| `BLOCKED` | Could not run: environment down, no login, missing master data, approval refused |
| `NOT_RUN` | Not attempted in this run |

## `summary_<case-id>.md` template

```markdown
---
case: no63_5-TC01
title: Main case — tiered equipment + all-day price, quantity 5 (create)
result: OK
reason:
steps_passed: 10
steps_total: 10
environment: local http://127.0.0.1:8000 (test DB)
tested_at: 2026-11-19
tester: AI (Claude) / <name>
---
# no63_5-TC01: Main case — tiered equipment + all-day price, quantity 5

- Data created: booking UK1004 (`/bookings/1286`), 2026/11/18 08:00 - 20:00

## Steps

| Step | Checklist action | Image | What the image shows | Result |
|---|---|---|---|---|
| 1 | Open 案件登録, choose KBF | `step01_create-form-kbf.png` | Form 案件登録, 施設 = KBF, memo template with ◆備品 | PASS |
| 6 | Memo ◆備品 lines | `step06_memo-equipment-lines.png` | `(1,100円)×1` / `(550円)×1` / `(770円)×3` | PASS |

## Cross-check

- Memo (incl. tax) 1,100 + 550 + 770 × 3 = 3,960 = 3,600 × 1.10
- Detail (excl. tax) 1,000 + 500 + 700 × 3 = 3,600; PDF 3,960 — all three agree.

## Notes

1. Deviations from the checklist, missing screenshots and why, data changed on the environment.

## Conclusion

10 / 10 steps PASS with screenshots; memo, detail and PDF agree. Result: OK.
```

Rules the report relies on (`DS evidence report` reads them; other layouts show as "not recorded"):

- The `## Steps` table keeps exactly these columns: `Step | Checklist action | Image | What the image shows | Result`. One row per checklist step; the first cell is the step number (`2`, or `2-3` for one row covering two steps; several rows for one step are merged, the worst result wins).
- `Result` is one of `PASS`, `NG`, `NO EVIDENCE`, `NOT RUN`; put explanations in the observation, not in this cell.
- `What the image shows` lists the exact screen values, separated by ` / `, in the order of the frame numbers (`1: 備品 (1,100円)×1 / 2: 合計 31,460円`); no paragraphs inside a table cell.
- `reason:` in the front matter is empty for OK and otherwise says in one line why the case is not OK (e.g. `Step 02 NG: memo rewritten when 編集 opens`) (the report's overview shows it); without it the first failing step is used.
- Other sections (`## Cross-check`, `## Notes`, `## NG — reproduction`, a precondition deviation) each become their own block in the report; `## Conclusion` is shown at the top of the case.

Write the summary in the language the user works in (the checklist carries all three). Mention every screenshot in the folder in the step table or the notes; `DS evidence report` flags images the summary does not mention and names it refers to that do not exist.

## After all cases

`DS evidence report --task <task>`, then report to the user: verdict, per-case results, NG details with screenshot paths, not-run/blocked cases and why, data created or changed on shared environments, and the path of `<root>/<task>/report.html`.
