---
name: verify-ui
description: "Use when inspecting rendered web or mobile UI, diagnosing layout defects, capturing screenshots or running UI E2E. Triggers (vi): kiểm tra UI, review giao diện, kiểm tra responsive, vỡ layout, tràn chữ, chụp màn hình."
metadata:
  version: "1.0.6"
  suite: devskills
---

# Verify UI

Visual evidence must be reproducible and honest: a pinned capture profile, synthetic data, explicit wait conditions, behavior assertions before pixels, and a baseline that only a reviewer can accept.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

**Review guidance (FE-014).** Load `ui-ux-pro-max` before reviewing a rendered UI, diagnosing broken layout or verifying a changed screen. Apply its relevant UX checks, such as reflow, touch targets, focus and contrast, against the project design and acceptance criteria. Include the checks actually applied in the review evidence. If the optional skill is unavailable, report that and continue with the [visual checklist](references/visual-checklist.md).

**UI E2E (FE-010, FE-014).** Inspect the rendered screens and states exercised as part of the E2E run. When the E2E runner covers a single viewport, use the same fixture to check the other applicable widths. Reproduce confirmed in-scope regressions during implementation, fix them via `implement-frontend`, and rerun the affected layout and behavior checks. For test-only work, report the reproduction and evidence.

**Viewport plan (FE-010).** Use the task and project's supported devices and breakpoints first. For new web UI, responsive fixes and layout audits without defined targets, check a narrow phone, tablet, laptop and desktop. Inspect both sides of affected breakpoints and any intermediate width where content starts to wrap. Use the [viewport selection checklist](references/visual-checklist.md#viewport-selection) for sizes and native app checks.

Themes: when the app supports light/dark, capture each changed screen with `--color-scheme light` and `--color-scheme dark` (System is the OS preference, which these two emulate) and check contrast, images and focus rings in both.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Fixing what the capture shows → **REQUIRED:** implement-frontend.
- Test data, seeds or a test server for the capture → **REQUIRED:** test-safely.

## Choose the runner (plan §20.1)

- The repo already uses **Playwright Test (JS/TS)** with `toHaveScreenshot()`: run that suite through `DS run-tests --profile integration_isolated --check-id ui.visual --junit … -- npx playwright test …` and read its report. Python Playwright has no `toHaveScreenshot`.
- Otherwise use the bundled capture: `DS screenshot`, which needs Playwright for Python and Chromium (`python3 -m pip install playwright && python3 -m playwright install chromium`). Without them the result is `BLOCKED` — never a fake image.

## Capture

```
DS screenshot --url http://127.0.0.1:3000/checkout --name checkout-pending \
  --viewport 360x800 --viewport tablet --viewport laptop --viewport desktop \
  --wait-for "[data-testid=order-total]" \
  --locale en-US --timezone UTC [--mask ".clock"] [--full-page] [--run <id>]
```

Only local URLs (add `--allow-host` solely for a host the user approved). The capture uses a fresh browser context, blocks requests to non-local hosts (listed in the manifest), disables animations and the caret, waits for fonts, records console and page errors, scans page text for secrets, and writes `<name>-<viewport>.png` plus a JSON manifest (profile id, browser version, viewport, locale, time zone, hashes). Pass each planned size explicitly using a preset or `WIDTHxHEIGHT`. With no `--viewport`, the command captures mobile + laptop.

## Compare with baselines

`--baseline-dir tests/visual/baselines` compares each capture with `<name>-<viewport>.png` there, or use `DS visual-diff --baseline B.png --current C.png [--mask X,Y,W,H]`. Images are never resized; thresholds come from `.devskills.toml [visual]`.

| Status | Meaning | Action |
| --- | --- | --- |
| `PASS` | same profile, within threshold | keep the evidence |
| `FAIL` | difference above threshold | inspect `*.diff.png`, fix or explain |
| `NEEDS_BASELINE` | no accepted baseline | show the capture to the user |
| `PROFILE_MISMATCH` | browser/OS/viewport/locale differ | re-run with the same profile |
| `CAPTURE_ONLY` | captured, not compared | never report as a visual pass |
| `BLOCKED` | app/browser/state unavailable | report the cause and what else was verified |

Baselines change only after a human reviewed the diff: `DS accept-baseline --current … --baseline … --approved-by "<reviewer>" --reason "<why>"` (appends to `BASELINE_APPROVALS.jsonl`). Never accept a baseline on your own to make a check green.

## Pipeline checklist

1. Route + state + acceptance criteria; synthetic fixture data (no real customer data on screen).
2. Assert behavior first (text, amounts, error messages via DOM/test runner), then capture.
3. Capture every state the change touches: loading, empty, error, success, permission denied; at the product's breakpoints.
4. Open and inspect the rendered screen or captured images using the [layout and wrapping checklist](references/visual-checklist.md#layout-and-wrapping). Check overflow, overlap, clipping, text wrapping, controls moving onto another row, and layout after adding rows/items. Use long content and enough synthetic items to exercise these transitions at target widths, including just above/below relevant breakpoints. Passing E2E assertions or a pixel comparison alone does not establish that the layout is usable.
5. Mask only dynamic regions unrelated to the change (clock, avatar) — never prices, errors or business data.
6. Check console/page errors and blocked external requests in the manifest.
7. Accessibility: keyboard flow, focus, labels, contrast; automated scanners help but do not prove WCAG compliance.
8. Review [product, user and business fit](references/visual-checklist.md#product-user-and-business-fit): flag unusual UI, confusing flows and mismatches with the established product type, user roles and business rules, even when behavior tests and visual comparisons pass. Report observations and suggestions; unrequested redesigns or business-rule changes remain outside the task.
9. Report behavior, visual and accessibility results separately. Include which screen/state, viewport, content cases and layout findings were actually inspected, with screenshot paths; mark uninspected layout as not checked. For UX/business findings, include evidence, affected user/task, impact, severity, confidence and a suggested improvement or clarification; distinguish confirmed defects from concerns needing confirmation and optional improvements. Screenshots and traces may contain personal data: keep them in the run folder; share only when the task allows.

Checklist per state and common issues: [visual-checklist.md](references/visual-checklist.md).
