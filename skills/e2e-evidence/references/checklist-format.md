# Checklist: format and how to derive the cases (E2E-002)

`<root>/<task>/checklist.json` is the source of truth; `DS evidence checklist --task <task>` validates it and renders `checklist.html`. Never hand-edit the HTML: edit the JSON and render again. A complete example: [checklist.example.json](../assets/checklist.example.json).

## Where the cases come from

Collect before writing a single case, and note in `source` what you used:

1. The prompt: the ticket text, the customer request, screens and values it names.
2. The branch: `git log <base>..HEAD`, `git diff <base>...HEAD --stat`, then the diff of each changed file. Every changed rule, branch, screen, query, PDF/CSV/calendar/email output is a candidate case. Base = the branch the task merges into (usually `main`).
3. Ticket and spec documents: the task folder in `docs/`, `specs/`, `deploy/fix/`, `ticket/`, `.knowledge/` mirrors, an existing checklist of the task (convert its cases; keep the original file untouched).
4. Existing automated tests of the task: their fixtures and assertions give concrete data and expected values.
5. The running screens (read-only browsing of a local environment) for labels and navigation, only when the target is local or approved.

If the branch and the prompt disagree, or a rule is ambiguous (money, permissions, deletion), ask one narrow question and mark the case's expected result as an assumption in `notes` until answered.

## Coverage — one case per behavior, not per screen

| Kind | Cases |
| --- | --- |
| Main path | The customer's request end to end, with the exact values they gave |
| Each rule branch | Every condition in the diff: on/off flags, thresholds, tiers, each side of a boundary |
| Switching | The same input changed back and forth (time, quantity, option) and the output follows |
| Create and edit | New record and edit of a saved record go through the same rule |
| Unaffected | Records/items the rule must not touch stay as before |
| Existing data | Records saved before the change are not rewritten until edited |
| Outputs | Every place the value appears: detail screen, PDF, CSV, email, calendar, API |
| Errors | Validation and permission failures the change can trigger |

Each expected result names the screen title and the value to check (`カレンダーメモ: ◆備品 line …`, `合計(税込) = 31,460円`): they become the red frames of the screenshot. Numbers are written out: inputs, the hand calculation and the expected screen text (`1,000 + 500 × 2 = 2,000`, `・DEMO Projector(1,100円)×1`).

## Schema `devskills.e2e-checklist/1`

A *text* is a string shown in every language, or `{"vi": "...", "en": "...", "ja": "..."}` with all three filled. `TODO` anywhere fails validation.

| Field | Required | Content |
| --- | --- | --- |
| `schema` | yes | `"devskills.e2e-checklist/1"` |
| `task` | yes | Task id = folder name, e.g. `no63_5` |
| `title` | yes | text |
| `summary` | | text: the request and what the run proves |
| `source` | | `{branch, base, ticket, docs: [...]}` |
| `environment` | | text: where the cases run (local URL, or the approved shared environment) |
| `page_size` | | cases per page in the HTML (default 10); every page shows its totals |
| `preparation` | | list of texts: master data, accounts, dates to prepare |
| `rules` | | text: the rule under test, in one or two sentences |
| `cases[]` | yes | see below |

Case fields:

| Field | Required | Content |
| --- | --- | --- |
| `id` | yes | `<task>-TC01`, `<task>-TC02`, … — the task prefix is enforced; folder = `<id>_<slug>` |
| `slug` | yes | lowercase words of the case, e.g. `edit-change-quantity` |
| `title`, `purpose` | yes | text |
| `preconditions` | | list of texts |
| `data` | | list of `{label: text, value: text}` with concrete values |
| `steps[]` | yes | `{action, data?, expected?, expected_block?}`; `expected_block` is exact screen text shown as a code block |
| `notes` | | text: assumptions, totals, what to skip when |

At least one step of every case has an expected result. Write the three languages yourself with the product's real screen labels (keep Japanese UI labels such as 登録する as they appear on screen in every language).
