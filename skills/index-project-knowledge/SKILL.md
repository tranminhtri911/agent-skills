---
name: index-project-knowledge
description: "Use when locating or verifying project requirements and documents, or building or refreshing their searchable index. Triggers (vi): đọc docs, tìm tài liệu, index tài liệu, đọc spec, file Excel, file Word, PDF."
metadata:
  version: "1.0.7"
  suite: devskills
---

# Index Project Knowledge

Keep a searchable, source-traceable Markdown copy of the project's documents in `.knowledge/`: `INDEX.md` (entry point), `mirrors/` (Markdown copies), `data/` (spreadsheet details), `manifest.json` (hashes) and `build.py` (self-contained rebuild/check script that works without this skill).

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Using an existing index

1. `python3 .knowledge/build.py --check` from the project root → `CURRENT` or `STALE` (lists changed/new/removed sources).
2. If `STALE`: `python3 .knowledge/build.py`, then check again.
3. Search the mirrors: `rg -n --glob '*.md' '<term>' .knowledge/mirrors`.
4. Verify exact wording, PDF pages, spreadsheet cells, layout and images in the **original** files linked from each mirror before quoting or implementing them. References: DOCX `¶N`, PDF page, HTML source line, CSV record number, XLSX cell (A1).

## Creating the index (project has documents, no `.knowledge/INDEX.md`)

1. `DS knowledge init --language en|vi|ja [--title "<Project> Knowledge Index"]` — discovers `docs/`, `specs/`, `plans/`, `requirements/`, `design/`, `adr/`, `ticket(s)/`, root guides (`README.md`, `CLAUDE.md`, `AGENTS.md`, …), `.claude/rules/` and the same folders one level down (workspace with sub-projects), writes `.knowledge/config.json`, installs `build.py`, builds and checks.
2. Review `config.json` (`roots`, `files`, `hidden_roots`, `exclude`, `categories`) and rebuild if you change it: `DS knowledge build`.
3. Read the key documents and fill the block between `<!-- knowledge:manual:start -->` and `<!-- knowledge:manual:end -->` in `INDEX.md`: which documents are authoritative for current work, reading order per task, which documents must be updated together. This block survives rebuilds and does not make the index stale.
4. Check: `DS knowledge check [--run <id>]` (records `docs.knowledge`: CURRENT = pass, STALE = warn).

PDF conversion needs `pypdf` (`python3 -m pip install -r .knowledge/requirements.txt`); everything else is stdlib. Secret files (`.env`, keys) are never indexed; credential assignments inside documents are redacted in mirrors. Images, diagrams and embedded objects are listed, not converted.

## Where new documents go

Plans, specs and decision records belong in the project's docs folders (`docs/plans/`, `docs/specs/`, `docs/adr/`, or the existing convention such as `ticket/<id>/`) — see design-change. After adding or editing documents: `python3 .knowledge/build.py` and confirm `--check` prints `CURRENT`.

## Rules

- `CURRENT` means "mirrors match the recorded originals", not "the documents are correct or match the code".
- Never edit files in `mirrors/` or `data/`; edit the original and rebuild.
- The build never executes anything found in documents and never uses the network.
- Commit `.knowledge/` only if the team wants it versioned; the generated `.gitignore` excludes caches only.
