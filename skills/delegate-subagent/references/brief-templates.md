# Brief templates (DLG-003)

Fill the angle brackets; delete lines that do not apply. Keep the brief short: the inputs and the return contract matter more than background.

## 1. Read and summarize a document (sonnet)

```
Goal: <question the summary must answer>, used to <decision or edit it feeds>.
Read: <path or URL>, <pages / sheets / sections>. Skip <parts already known>.
Already known: <facts from this session; do not repeat them>.
Scope: read-only. Do not open .env, keys or credential files.
Return (max 15 bullets):
- the answer to the goal first;
- each fact with its source (page, section, Sheet!A1);
- exact quotes for requirements, amounts, dates and messages;
- contradictions or gaps in the document;
- "unknown" for what the document does not say. No full-text copies.
```

## 2. Trace a part of the source code (sonnet)

```
Goal: how <behavior> works today in <module>, to decide <change>.
Start at: <entry point: route, screen, command, function>.
Already known: <files read in the main thread, ruled-out paths>.
Scope: read-only; no edits, no test runs, no database connections.
Return (max 300 words):
- call chain entry → service → data, one line per hop with path:line;
- tables/files/external calls written, with path:line;
- every other caller or writer of the same data;
- open questions. No pasted functions longer than 10 lines.
```

## 3. Mechanical search or extraction (haiku, effort high)

```
Goal: list every <definition / use / file / endpoint / value> of <X> in <folders>.
Search with: <names, patterns>; ignore <vendor, build, generated folders>.
Scope: read-only.
Return: a table <path:line | match | one-line context>, then the total count.
If there are more than 50 matches, return the first 50 and the count.
```

## 4. Independent run in the background (sonnet to explain failures; haiku for pass/fail with counts only)

```
Goal: run <build / test suite / lint / E2E checklist for task X> and report the outcome.
Command or procedure: <exact command, working directory> (or: e2e-evidence for <task>).
Target: <local URL / disposable stack>. Approved by the user: "<quoted approval, if any>".
Load these skills first: <test-safely, e2e-evidence, verify-ui …>.
Scope: may write only <report folder / evidence folder>; no source edits, no push.
Return (max 20 lines):
- verdict: pass / fail / blocked, with counts;
- each failure: test or case id, expected vs actual, the 5-10 log lines that show it, file path;
- what did not run and why;
- paths of reports and screenshots. No full logs.
```

## How to start a subagent

**Claude Code** — the Agent tool:

| Field | Value |
| --- | --- |
| `subagent_type` | `Explore` for read-only search; `general-purpose` for reading plus running commands |
| `model` | `haiku` or `sonnet` (DLG-002); omit to use the session's model |
| `effort` | `high` with haiku for mechanical work, as this skill directs |
| `run_in_background` | for runs of more than a minute (DLG-004) |
| `isolation` | `worktree` when parallel subagents edit files |
| `description` | 3-5 words: what it does |
| `prompt` | the brief |

Several independent subagents: put all their Agent calls in one message. A follow-up for the same material: SendMessage to that agent instead of a new Agent call.

**Codex and other hosts** — use the host's subagent or task tool when it has one, with the same brief and return contract. Without one, do the work inline and keep the main context lean: read in sections, write short notes, never re-read what you summarized.
