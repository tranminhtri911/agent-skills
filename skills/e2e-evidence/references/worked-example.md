# Worked example: a real manual run this skill was learned from

A booking system ticket ("the all-day equipment price must appear in the calendar memo") was tested by hand on staging and the evidence arranged afterwards. The layout, names and summaries below are what the skill reproduces; values are shortened.

## Folder

```
evidence/
  no63/
    No63_5_Checklist.html                      the checklist (now: checklist.json + checklist.html)
    summary.html                               the overall report (now: report.html)
    TC1_main-case-tiered-allday-qty5/
      step02-03_create-form-basics-venue-time.png
      step04_memo-allday-plan-line-and-estimate.png
      step05_add-equipment-qty5.png
      step06_memo-equipment-lines.png
      step07_save-success-uk1004.png
      step08_booking-detail-equipment-calculation.png
      step09_invoice-pdf-uk1004.png
      summary.md                               (now: summary_<case-id>.md)
    TC4_normal-price-plus-allday/
      step00a_precondition-master-equipment-top.png
      step00b_precondition-master-equipment-allday-settings.png
      step01a_edit-uk1004-venue-501.png
      ...
    TC5_equipment-without-allday-not-affected/
      step02-03a_form-no63-4-qty3-and-no63-5-qty2.png
      extra_booking-detail-after-update.png
      extra_invoice-pdf-after-update.png
```

What made it useful, and is now a rule:

- One folder per case, screenshots named by the step they prove and by what they show (E2E-001, E2E-004).
- Several screenshots for one step get `a`, `b`, `c`; one screenshot for two steps gets `step02-03`; preconditions `step00`; supporting proof `extra_` (E2E-004).
- Each summary has a step table *Step | checklist content | image | what the image shows | result*, then a cross-check of amounts between memo, detail screen and PDF, then notes and a conclusion with `n / m steps` (E2E-006).

## Findings the summaries recorded — and the rule each became

| Observation in the real run | Rule |
| --- | --- |
| Step 1 and step 10 had no screenshot, so the case could not be fully OK | No OK without a screenshot per step (E2E-006) |
| The checklist asked for the quotation PDF (見積書PDF); the screenshot was the invoice PDF (請求書) | Deviation noted, result lowered unless the purpose is still proven (E2E-009) |
| The edit-screen case had no screenshot of the memo, its main point | Capture the value under test, not only the form (E2E-004) |
| "Old booking unchanged" was run on a booking created after the deploy | Data deviations lower the result; repeat on real old data (E2E-009) |
| Master data form screenshots were taken before saving; duplicates might exist | Record data created/changed on the shared environment (procedure step 8) |
| Calendar showed 6:00 instead of 8:00 because the test calendar was GMT+7 | Explain environment differences instead of calling them defects (E2E-005) |
| Every amount was recomputed by hand: memo incl. tax = detail excl. tax × 1.10 = PDF | Recompute numbers yourself (E2E-005) |
| Staging bookings were created and edited many times during the run | Approval and a data list for non-local runs (E2E-003) |

## Summary excerpt

```markdown
| Step | Checklist content | Image | What the image shows | Result |
|---|---|---|---|---|
| 6 | ◆備品 in the memo | `step06_memo-equipment-lines.png` | `・No63_1-Cider Equipment(1,100円)×1` / `(550円)×1` / `(770円)×3`; estimate 備品料金 3,600円, 合計 7,260円 | PASS |
| 10 | Saved memo equals step 6 | (none) | No screenshot of the saved memo | NO EVIDENCE |

## Conclusion
8 / 10 steps PASS with screenshots; steps 1 and 10 have no screenshot. No difference between memo, detail and PDF. Result: PARTIAL.
```
