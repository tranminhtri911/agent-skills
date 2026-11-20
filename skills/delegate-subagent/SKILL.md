---
name: delegate-subagent
description: "Use when a task needs to read a new document, source tree or reference beyond what this session already holds, or has independent long-running work (build, test suite, E2E run, log analysis) that can run beside the main thread. Keeps the main context small by delegating to subagents with their own context. Triggers (vi): subagent, tách agent, chạy song song, chạy nền, đọc tài liệu khác, tóm tắt tài liệu, tiết kiệm context, tràn context."
metadata:
  version: "1.0.8"
  suite: devskills
---

# Delegate Subagent

The main context is the scarce resource of a session: every file, log and page read into it stays there until compaction, and a full context degrades every later step. A subagent has its own context. It reads, analyses or runs, and returns only the conclusion. Delegate so that the main thread keeps the user's requirement, the decisions and the edits; keep in the main thread whatever needs its judgment or the user's approval.

## Where each piece of work runs (DLG-001)

**First, count the independent tasks in the request.** Two or more reading, search or run tasks that do not depend on each other (a numbered list, "and also") → one subagent per task (or per batch, DLG-004), all launched in one message so they run in parallel, whatever the size of each; the main thread only merges the answers. This check comes before the table: the size rows below apply only to a request with a single task.

| Work | Runs in | Model (DLG-002) |
| --- | --- | --- |
| Material already read into this session (files, documents or output the main thread has opened) | main: reuse what you have; never re-read it through a subagent. A file the request only names, not yet opened, is new material | — |
| The request's only task is a small lookup with a known target: one file or section under about 300 lines, one grep | main: delegating costs more than reading | — |
| A new document, source tree or reference not read yet and larger than that: spec PDF/Excel/Word, another module, a library's docs, several files, a log over about 500 lines | subagent: analyse or summarize, return the conclusion with sources | sonnet |
| Mechanical search or extraction over many files: where X is defined or used, list files or endpoints, pull fields from a known format | subagent | haiku, effort high |
| Independent long-running work that shares no files, ports or data with what the main thread does next and does not wait on it: build, full test suite, lint, E2E run by checklist, screenshot verification | background subagent; the main thread keeps working | chosen by what the main thread needs back: sonnet when it will act on failures (expected vs actual, cause), the default for test suites and E2E runs; haiku when pass/fail with counts and failing names is enough |
| Hard judgment: root cause, design choice, money/security/permission review, conflicting evidence, the final verification of a claim | main decides; gathering new evidence for it (reading code or documents not yet read) may go to a subagent first | main model |
| Anything that needs the user's approval: cloud, non-local database, staging data, push, posting, sending | main asks first (OPS-011..013) and runs short approved actions itself (a few commands, about a minute); only a longer approved run (an E2E checklist on staging) goes to a subagent, with the approval quoted in its brief | — |
| Code edits | main by default; a subagent edits only files nobody else touches during its run: one writer per file, also for edits made one after another | — |

Thresholds are guides for a single-task request, not limits: a 200-line file read once is cheap; a 2,000-line log is not, however it arrives. When the host has no subagent tool, say so in one line and keep the main context lean instead: read in sections, keep short notes, never re-read what you already summarized.

## Choose the smallest model that does the job (DLG-002)

- **haiku** (effort high where the host offers it): finding, listing, extracting, running a command and reporting pass/fail with the failing lines. Clear question, checkable answer.
- **sonnet**: reading and summarizing documents, tracing a module's flow, comparing versions, running an E2E checklist and judging screenshots.
- **main model**: ambiguity, design, money/security/permissions, and anything a sonnet result left uncertain on a point that matters.
- Escalate once, do not loop: an incomplete haiku result gets that part rerun with sonnet; an incomplete sonnet result is finished in the main thread.

## Write a brief the subagent can act on alone (DLG-003)

The subagent knows only its brief. Every brief states:

1. **Goal**: one sentence, and what the answer is for (the decision or edit it feeds).
2. **Inputs**: exact paths, URLs, pages, sheets, commands; what is already known or ruled out, so it is not repeated.
3. **Scope**: read-only, or exactly what it may create or change; nothing outside.
4. **Safety**: no `.env`, keys or credential files; no cloud, non-local database, push or external sends unless the brief quotes the user's approval for that exact action; the skills it must load for the work it does (subagents do not inherit loaded skills; read-only analysis needs none).
5. **Return contract**: format and length limit (e.g. at most 15 bullets or 300 words), each fact with its source (`path:line`, page, `Sheet!A1`), exact quotes for wording that matters (requirements, amounts, messages), `unknown` instead of a guess, no file dumps.

Ask a question; do not hand over your hypothesis to be confirmed, or it comes back confirmed. Templates per kind of work: [brief-templates.md](references/brief-templates.md).

## Run it (DLG-004)

- Foreground when the next step needs the answer (a summary, a search result); background when the main thread has other work meanwhile (a build, a test suite, an E2E run). Background completion arrives as a notification: do not poll, do not sleep.
- Launch independent subagents in one message so they run in parallel.
- While they run, continue only work that does not touch their files, ports or data.
- Never do the delegated work yourself as well, and never state a result that has not arrived; if the user asks, say it is still running.
- At most about 3–4 subagents at a time unless the user asks for more: each one costs tokens the user pays for.
- Many similar items (every spec file, every screen, every endpoint): the user names the goal and the scope, not each item. List the items yourself (a glob or one search), split them into 3–4 batches of related items, give each batch to one subagent with the same brief and the same table format, then merge the tables in the main thread. Items left over wait for the next round; never one subagent per item.
- Parallel writers work on separate files. An isolated worktree each keeps their checkouts apart; it does not make two edits of the same file safe to merge.
- A follow-up question about the same material goes to the same subagent (it keeps its context), not to a new one.

## Take the result back (DLG-005)

- A subagent's mistakes arrive in the same confident tone as its facts. Before editing code or telling the user, open the cited source for the one or two facts the next step depends on.
- Keep only the conclusion and its sources in the main thread. The user does not see the subagent's report: relay what matters in your own words.
- Contradictions, `unknown` on a point that matters, or a missing source: check it in the main thread or send one narrower question.
- In the final report, name what was delegated and which of its facts you verified.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Reading a 40-page spec into the main thread to answer one question | Sonnet subagent with the question and a return limit (DLG-001) |
| "1. read the price master 2. read the evidence folder" done one after another in main because each file is small | Two tasks → two subagents in one message; size rows apply to single-task requests only (DLG-001) |
| A subagent to re-read the file the task started from | Reuse what the main thread already has |
| Opus for "find every caller of X" | Haiku, effort high (DLG-002) |
| "Look at the billing code" | Goal, paths, scope, return contract (DLG-003) |
| "Confirm the bug is in `calc_fee`" | "Which function produces the wrong fee for input …? Cite lines." |
| Waiting idle on a 10-minute E2E run | Background subagent; keep working on what does not overlap (DLG-004) |
| 26 spec files → 26 subagents | 3–4 batches, one subagent each, same table format, merged in main (DLG-004) |
| Two subagents editing `routes.py` | One writer per file; a worktree each does not make it safe (DLG-004) |
| Pasting the subagent's whole report to the user | Relay the conclusion; verify the facts it rests on (DLG-005) |
| A subagent told "test on staging" without the approval text | Ask the user first; quote the approved cases and data in the brief |
