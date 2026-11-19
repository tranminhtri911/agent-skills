# Run the cases and capture screenshots (E2E-003, E2E-004)

## 1. Decide the target before the first click

Classify the URL and what stands behind it (dev-orchestrate OPS-014):

| Target | Action |
| --- | --- |
| Local app with a database created for the run (docker compose test stack, `php artisan serve` on a test DB, seeded synthetic data) | Proceed |
| Local container or port that serves a shared environment: its domain is the staging/production domain, its database holds shared data, its calendar/email/payment integrations are live | Treat as non-local |
| Staging / dev server / shared test server | Ask first (below) |
| Production | Never run test cases; read-only viewing only on the user's explicit request |
| Unknown | Read the compose file, nginx/server config and the `.env` *names* the app loads (not values) to resolve it; still unknown → non-local |

Before proposing `docker compose up`, `migrate`, `seed` or any reset as "the local environment", prove it is not the shared one (local reads, no approval needed):

1. Container names in the compose file you would use (`container_name:`) versus the running containers (`docker ps`) and the other compose files (`docker-compose.prod.yml`, `docker-compose.stg.yml`).
2. Which containers the web server routes the real domains to (`nginx/*.conf` `upstream` / `fastcgi_pass` / `proxy_pass`, `server_name`).
3. If the dev compose file reuses a container name that a production or staging compose file or a public domain uses, `up`, `down`, `migrate` or `seed` would replace or write the live system: never run them; ask for a separate, isolated test stack (other project name, container names, ports and a fresh database) instead.

Asking for a non-local run (OPS-013 dialog, e.g. `🧪 Chạy E2E · STG`): list the cases, the records each creates, edits or deletes, external effects (Google Calendar events, emails, PDFs sent, payments), the account used and the cleanup. Approval covers exactly that list; extra cases or data need a new approval. While waiting, finish the checklist and everything offline.

Logins: use the test account the user names or the project's seeded test user. Never read `.env`, credential files or browser profiles to find a password; ask. Never type real customer data.

## 2. Choose how to drive the browser

1. **The project's E2E suite** (Playwright Test, Cypress, Dusk, Selenium) — run it through test-safely `DS run-tests --profile integration_isolated ...`; configure its screenshot output into the case folders, or copy the produced screenshots there and rename them by step.
2. **An agent-driven browser** — a browser tool of the host (Playwright MCP, built-in browser, Chrome extension), or a short Playwright script kept outside the repository (scratch directory), using an already installed Playwright and browser. Do not add a dependency to the project for this.
3. **Manual run by the user** — the user does the steps and gives the screenshots; you map each to its step, rename it and verify it like any other.

Do not install packages or browsers without the user's approval.

## 3. Capture rules

- At least one screenshot per step that has an expected result; take the screenshot after the screen settled (spinner gone, estimate recalculated, toast shown).
- The value under test is inside the frame. Long forms: scroll to the section, or capture the element, and add `step02b_...` for the next part.
- Names: `stepNN[a-z]_<what-is-shown>.png`, lowercase, words joined by `-`: `step03b_booking-detail-amounts-qty3.png`. Preconditions `step00a_...`; extra proof `extra_...`; one image for two steps `step02-03_...`.
- Viewport: desktop 1440×900 unless the case is about another device; use the same viewport for the whole task.
- Record the record ids/numbers the run creates (e.g. booking UK1004) — the summary lists them and the cleanup uses them.
- Do not capture secrets (tokens, passwords, API keys); mask or retake if one appears.

## 4. Minimal Playwright (Node) step capture, outside the repository

```js
// capture.cjs — run from a scratch directory: node capture.cjs
const { chromium } = require('playwright'); // an installed copy; do not add it to the project
(async () => {
  const caseDir = '/abs/path/<root>/<task>/<case-id>_<slug>';
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'ja-JP', timezoneId: 'Asia/Tokyo' });
  const shot = async (name) => page.screenshot({ path: `${caseDir}/${name}.png`, fullPage: false });
  await page.goto('http://127.0.0.1:8000/login');
  // ... log in with the test account the user gave
  await page.goto('http://127.0.0.1:8000/bookings/create');
  await shot('step01_create-form');
  await page.fill('#quantity', '3');
  await page.waitForTimeout(1000); // the estimate recalculates after input
  await page.locator('#calendar-memo').scrollIntoViewIfNeeded();
  await shot('step02_memo-equipment-lines');
  await browser.close();
})();
```

Selectors and URLs come from the real screens; read the page before writing the script. After the run, open every screenshot (step 5 of the skill) — a script that finished is not a passed case.
