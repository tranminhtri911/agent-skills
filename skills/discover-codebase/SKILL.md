---
name: discover-codebase
description: "Use when about to change, specify or estimate work on code you have not fully traced — a new ticket, an unfamiliar feature, a rename or type change, a bug with an unclear cause, a question about which tables, screens or APIs a change affects, or a diff that grows beyond the files already read. Triggers (vi): code này chạy thế nào, ảnh hưởng tới đâu, bảng nào bị tác động, lỗi chưa rõ nguyên nhân, tính năng chưa quen, khả thi. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.3"
  suite: devskills
---

# Discover Codebase

Build an evidence-based picture of a feature before editing: screens, routes, classes, functions, variables, tables, side effects, tests and who else writes the same data. The tool lists facts; you read the code and fill in meaning.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Procedure

1. **Project knowledge first.** If `.knowledge/INDEX.md` exists: run `python3 .knowledge/build.py --check` (rebuild when `STALE`), search `.knowledge/mirrors` with `rg`, and verify exact wording, PDF pages and spreadsheet cells in the linked originals. If the project has documents (`docs/`, `specs/`, tickets, Office/PDF files) but no index, create one with index-project-knowledge.
2. **Repository instructions.** Read `CLAUDE.md`, `AGENTS.md`, `.claude/rules/`, `CONTRIBUTING`, lint and editor configs. They define conventions you must keep.
3. **Inventory.** `DS inspect --feature <keywords> [--run <id>]` writes `context-map.json` and `context-map.md`: stack and versions from manifests, test commands, DB engines, feature files with roles, symbols and their callers, DB entities, secret files (never read), and uncommitted changes to preserve.
5. **Code graph (optional, CodeGraph).** `inspect` reports `code_graph` in the context map. The flag is `--codegraph auto|on|off` (default: env `DEVSKILLS_CODEGRAPH`, then `.devskills.toml [integrations] codegraph`, then `auto`).
   - When `code_graph.available` is true, use the read-only CLI instead of grep + read loops: `codegraph explore "<feature words>"`, `codegraph callers <Symbol> --json`, `codegraph impact <Symbol> --depth 2 --json`. `inspect` already saved an exploration (`codegraph-explore.md`) and the tests affected by current changes.
   - Read a file directly when CodeGraph prints a ⚠️ pending-sync banner for it, and always before editing the exact lines.
   - Not indexed or `off`: continue with `inspect` + reading. Never run `codegraph init`/`index` yourself — tell the user it is available (`codegraph init` creates `.codegraph/` and a file watcher).
6. **Read along the call chain**, in the suggested order: route/screen → service/use case → repository/model → migration/schema → jobs/webhooks → tests. Read callers of anything you will change (CTX-001), including generated clients, serializers, reflection and string-based references (CTX-002).
7. **Data and side effects.** For every table touched: transaction boundary and every writer of that table — API, admin, workers, batch, imports, migrations (CTX-003). For multi-tenant code trace tenant identity through UI → API → query → cache → job (CTX-004). List external effects: payments, email/SMS, queues, files, third-party APIs.
8. **Fill the context map** (`agent_must_fill`): confirmed entry points, call chain, invariants, transaction boundaries, other writers, external side effects, trust boundaries, facts seen in code vs assumptions vs unknowns, risk level.
   For maintenance/update/refactor, also identify the full old commit and working-tree snapshot, read the old implementations/callers, and record preserved cases versus requested differences (CHG-004/005). Specs support this comparison; report conflicts with observed old behavior before treating them as a change requirement. Details when write-maintainable-code is available: its `references/changing-existing-code.md`, preservation contract.
9. **Decide the scope.** Files to change, files affected, confidence. If new findings require work beyond the user's request, explain the proposed expansion and wait for approval; continue the work already in scope (CTX-007, AGENT-012). A revised plan alone does not authorize unrelated changes.
10. **Route the next skills.** The map decides them, not the wording of the task — load each with the Skill tool before analyzing or editing that part: tables written, deletes, transactions or locks → change-database; routes and contracts → design-api; services, jobs, batches → implement-backend; screens → implement-frontend and verify-ui; external calls or jobs that must not die halfway → design-reliability; auth, tenants, user input → review-security; loops over many rows, workers, caches → review-performance; tests or test data → test-safely. Name them in the output.

## Rules

- CTX-006: never import or run application modules just to explore; read and parse statically.
- AGENT-003: do not open `.env`, keys or credential files for context; `inspect` lists them without reading.
- CTX-009: new code extends the project's own bases, helpers and reference module; a new base class, helper, library or pattern needs a stated reason (nothing existing fits) in the design.
- DES-007: note the patterns in use and the import direction between layers (reference module + `rg` on imports); they are the architecture to follow.
- CODE-011: note the enums/choices/constant groups, settings and i18n catalogues the feature touches (`inspect` lists values and key constants) so the code uses them instead of literals.
- CTX-008: claim understanding only for what you read ("the order flow"), not the whole system.
- Keep uncommitted developer changes; `inspect` prints them first.

## Output to the user (short)

Conventions to follow (reference module + bases/helpers to reuse), entry points, the call chain in one or two lines, data touched and other writers, invariants, side effects, tests that cover it, unknowns that change the design, the proposed scope, and the skills routed next (step 10). Example invariants: "one successful charge per payment request", "stock never negative", "tenant A never reads tenant B's orders".

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Editing the first file that matches the keyword | Read entry point and callers first |
| Ignoring the batch job that writes the same table | Search for the table name and model across jobs/commands |
| Trusting the ORM model over the migrations | Read the actual migrations/schema in the repo |
| Treating `inspect` hits as understanding | Hits are leads; confirm by reading the code |
| Mapping a delete/lock/transaction flow, then specifying it without change-database | Step 10: the tables in the map route to change-database before any spec or edit |
| Writing a new API client, error class or base model next to the existing one | Reuse the project's base listed in "Project conventions"; extend it if it lacks something |
| Copying a pattern from the internet instead of from the repo | Imitate the reference module's structure, naming and tests |
