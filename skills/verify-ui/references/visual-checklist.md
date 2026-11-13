# Visual verification checklist

## Per changed screen

| State | Capture? | Behavior assertion before capture |
| --- | --- | --- |
| Loading | yes (skeleton/spinner) | indicator visible, actions disabled |
| Empty | yes | empty message + primary action |
| Success | yes | key values (amounts, names) match fixture |
| Validation error | yes | message next to the field, focus moved |
| Server error / timeout | yes | retry option, no data loss |
| Permission denied | yes | no restricted data rendered |
| Pending (payments) | yes | "verifying" state, not "failed" |

Viewports: every target device; by default mobile 390×844 and laptop 1280×800, plus tablet 768×1024 or desktop 1440×900 when targeted. Mobile apps: iOS simulator and Android emulator, small and large phone.

## Layout and wrapping

Inspect the rendered screen or open the captured images for each affected state and target viewport. Use the existing design and acceptance criteria to judge whether wrapping and row placement are appropriate.

| Check | Exercise | Expected result |
| --- | --- | --- |
| Overflow, overlap and clipping | Narrow target width, long content, expanded sections | No unintended page-level horizontal scrolling, overlapping elements, cut-off text or hidden actions; intentional table scrolling stays within its container |
| Text wrapping | Long labels, names, validation messages and supported locales; unbroken URLs/IDs where relevant | Natural line breaks within the container; no isolated or clipped characters, unintended truncation, or unreadable button labels; intentional truncation follows the design |
| Controls moving to another row | Filters, toolbar actions, form fields and card grids near the width where they wrap | Logical reading/action order, consistent alignment and spacing; labels remain associated with their fields and primary actions remain usable |
| Added rows/items | One item, several items, and enough items to create another row or require scrolling; exercise add/remove where supported | New rows keep column alignment and spacing; surrounding sections reflow without overlap; totals, pagination and actions remain reachable |
| Height growth and scrolling | Multiline content/errors, open dialogs, expanded content and sticky/fixed elements | Containers grow or scroll as designed; footers, dialogs and sticky elements do not cover content or controls |
| Responsive transitions | Target widths and just above/below relevant breakpoints or observed wrapping thresholds | No broken intermediate layout, unexpected ordering or excessive gaps when columns stack or controls wrap |

Use synthetic fixtures that reach the relevant transitions rather than only short text and a single item. Where useful, add DOM assertions for specific overflow, visibility or alignment invariants; these support inspection but cannot judge whether line breaks look appropriate. Record the screen/state, viewport, fixture case, screenshot path and any issue. A capture that was saved but never opened has not been visually reviewed; a matching baseline can preserve an existing layout defect.

## Product, user and business fit

Report UI/UX concerns found in the inspected scope even when the layout is intact and automated checks pass. Establish the product type, target users, roles, main tasks and business rules from the task and existing project evidence. Evaluate SaaS, admin and end-user experiences in their actual context; when context is missing, state the assumption and flag the concern for confirmation.

| Review area | What to flag |
| --- | --- |
| Visual consistency and hierarchy | Unexplained differences in components, spacing, typography or interaction patterns; competing primary actions; important information visually buried relative to the user's task |
| User and role fit | Technical/admin terminology in an end-user flow; irrelevant controls; actions that conflict with the user's role or permissions; missing context about whose data or account is being changed |
| SaaS context, where applicable | Unclear active workspace/account; confusing plan, usage, billing or permission information; onboarding or empty states that leave the user without an appropriate next action |
| Business meaning | Labels, statuses, totals, validation and enabled actions that contradict established rules or observed behavior; success wording before completion; unclear consequences of consequential actions |
| Task flow and feedback | Unclear next steps, unnecessary repeated input, hard-to-find frequent actions, lost context, ambiguous save/submit results, or errors without a useful recovery path |

For each finding, record the screen/state, viewport, screenshot or observed interaction, affected user/task, expected behavior and its source, impact, severity, confidence, and a suggested improvement or question. Label it as a confirmed defect, a concern needing confirmation, or an optional improvement. Keep evidence separate from inference; a stylistic preference alone is an optional suggestion, and a SaaS convention alone does not establish a business requirement. Do not hide observations because they predate the change; identify pre-existing findings separately from regressions. Report findings outside the requested fix scope without implementing an unrequested redesign or business-rule change.

## Determinism

- Synthetic data with fixed dates, amounts and names; fixed locale and time zone.
- Fonts served locally (external font requests are blocked and change rendering).
- No random avatars/ads/third-party widgets; mock them or mask them with a reason.
- Wait for a concrete element/text, never a fixed sleep.

## Common flakiness causes

| Symptom | Cause | Fix |
| --- | --- | --- |
| 1-2 px shifts between runs | font loading, sub-pixel layout | local fonts, wait for `document.fonts.ready` (done by the tool) |
| Whole image differs | different browser/OS/viewport | same capture profile (`PROFILE_MISMATCH` warns) |
| Random regions differ | time, animations, carousels | fixed clock, animations disabled, mask with reason |
| Missing content | captured before data loaded | `--wait-for` selector of the final content |

## Accessibility quick pass

Tab through the page: every control reachable, visible focus, logical order · inputs have labels · errors announced (`aria-live`) · contrast of text and controls · images have alt text · no keyboard traps in dialogs.
