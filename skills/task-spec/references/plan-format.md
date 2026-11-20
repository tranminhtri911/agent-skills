# The plan: format, blocks, diagrams, readability (SPEC-003, SPEC-008, SPEC-009)

Write the plan as JSON in a scratch file (not in the task folder) and render it with `DS spec build --task <task> --plan <file> --checklist <file>`. `plan.html` embeds the JSON; `DS spec source --task <task> --part plan --out <file>` gives it back for the next edit. Example: [plan.example.json](../assets/plan.example.json).

## Top level

| Field | Required | Content |
| --- | --- | --- |
| `schema` | yes | `"devskills.task-plan/1"` |
| `task` | yes | Task id = folder name |
| `title` | yes | Text; the page does not repeat the task id when the title starts with it |
| `summary` | | One or two short sentences under the title |
| `source` | | `{ticket, branch, base}` |
| `blocks[]` | yes | `{id, title?, items[]}` or `{id, not_applicable: "<reason>"}`; standard ids below; extra blocks with their own id and `title` go after them |
| `subtasks[]` | yes | `{id: "task01", slug, title, estimate_hours, depends_on?: [...], status?: "todo" \| "done"}`; file `sub_tasks/<id>_<slug>.md` |

A *text* is a plain string or `{"vi", "en", "ja"}`. `TODO` anywhere fails validation.

**Item:** `{title, body?, diagram?, items?, status?, owner?, tag?}` — at least one of `body`, `diagram`, `items`.
`body` is Markdown (lists, tables, code blocks, `inline code`, **bold**, links). `items` are child items (up to 3 levels), each collapsible on the page. `status` (`open`, `answered`, `n/a`) and `owner` are for `confirm` items; `tag` is a short label shown as a chip.

## Blocks (pages of plan.html, in this order)

| id | Page | Must contain |
| --- | --- | --- |
| `overview` | Tổng quan | Goal (2–4 lines); a table mapping each sentence of `require.md` to the part of the plan that handles it; scope in / out |
| `current_flow` | Flow hiện tại | **Diagram** of today's path from the code; a short list of the functions/routes/jobs on it with file paths; known problems with evidence |
| `target_flow` | Flow sau khi triển khai | **Diagram** after the change with `new` / `changed` / `removed` nodes; every entry path (screen, API, batch, import); outputs |
| `changes` | Cách sửa chi tiết | One item per file or module, child items per change: what, why, new/changed signatures, schema/migration, config; reused helpers |
| `impact` | Ảnh hưởng | Child items: existing logic and callers (search results), stored data, other screens/jobs/APIs/outputs, performance/locks, permissions, what stays unchanged |
| *(subtasks)* | Chia task nhỏ | Built from `subtasks` and the sub task files |
| `verify` | Cách verify | Environment, data to prepare, what to open, exact values to see; amounts recomputed by hand |
| `test` | Cách test | Unit tests (file, cases), integration tests (isolated DB), E2E/manual by checklist (the page lists the checklist cases) |
| `risks` | Rủi ro | One item per risk: likelihood/impact, mitigation, stop condition (DES-006) |
| `confirm` | Vấn đề cần confirm | One item per question: what is unclear, options with your recommendation, `owner`, `status` |
| `estimate` | Estimate | Assumptions (people, hours/day, review); the sub task table, total and remaining are added automatically |
| `deploy` | Cách deploy | Ordered steps, migrations/data fixes, config, verification after release, rollback or roll-forward |

## Diagram (SPEC-008)

```json
"diagram": {
  "nodes": [
    {"id": "open", "label": "Mở 編集", "kind": "start"},
    {"id": "changed", "label": "Giờ hoặc thiết bị đổi?", "kind": "decision", "state": "new"},
    {"id": "memo", "label": "buildMemo(estimateRows)", "kind": "step", "state": "changed"},
    {"id": "save", "label": "bookings", "kind": "data"},
    {"id": "gcal", "label": "Google Calendar", "kind": "external"}
  ],
  "edges": [
    {"from": "open", "to": "changed"}, {"from": "changed", "to": "memo", "label": "có"},
    {"from": "memo", "to": "save"}, {"from": "save", "to": "gcal", "label": "job"}
  ]
}
```

- `kind`: `start`, `end`, `step`, `decision`, `data`, `external`. `state`: `same` (default), `new`, `changed`, `removed`.
- Labels are short (a function, a screen, a question); `\n` breaks a line. Edge labels name the condition or trigger.
- Nodes are laid out top to bottom by their order on the path; an edge back to an earlier node is drawn as a loop on the right.
- The page also offers the flow as text (for search and screen readers).

## Readability (SPEC-009)

`DS spec build` checks every body and sub task file:

| Rule | Limit | Finding |
| --- | --- | --- |
| One line of prose | 200 characters | SPEC-LONG-LINE (fails) |
| One table cell | 140 characters | SPEC-LONG-LINE (fails) |
| One item | 18 non-empty lines | SPEC-ITEM-TOO-LONG (warns) |

Write one fact per line, as lists; put detail in child items; prefer tables for comparisons; cite code as `path/to/file.ext` + function; label assumptions and proposals.
