"""E2E / manual test evidence by checklist: `evidence init`, `evidence checklist`, `evidence report`.

Layout under the evidence root (gitignored, one folder per ticket or task):

    <root>/<task>/checklist.json            cases: steps, data, expected results (vi / en / ja)
    <root>/<task>/checklist.html            rendered checklist: left menu, pages with totals, checkboxes
    <root>/<task>/<case-id>_<slug>/         one folder per case
        stepNN[a-z]_<what-is-shown>.png     screenshots named by step after verification
        summary_<case-id>.md                front matter `result: OK|NG|PARTIAL|BLOCKED|NOT_RUN` + step table
    <root>/<task>/report.html               the one report: every case OK/NG with reasons and links, then each
                                            case's checklist steps with result, observation and screenshots

The commands only arrange files and render HTML. Running the cases and judging each screenshot is the
agent's (or tester's) job; `report` refuses to call a case OK without its summary.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from devskills.evidence_templates import (
    CHECKLIST_SCRIPT,
    CHECKLIST_STYLE,
    PAGE_STYLE,
    PLAN_STYLE,
    REPORT_SCRIPT,
    REPORT_STYLE,
    UI_LABELS,
)
from devskills.fsutil import atomic_write_text, read_json, resolve_repo_root, run_git, utc_now_iso
from devskills.models import (
    EXEC_COMPLETED,
    GATE_BLOCKED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    Finding,
    UsageError,
)
from devskills.output import emit_result, format_findings

SCHEMA = "devskills.e2e-checklist/1"
LANGUAGES = ("vi", "en", "ja")
DEFAULT_PAGE_SIZE = 10
# Searched in this order when neither --root nor .devskills.toml [evidence].root names the evidence root.
ROOT_CANDIDATES = ("evidence", "deploy/evidence", "docs/evidence", "tests/evidence", "e2e/evidence")
CHECKLIST_JSON = "checklist.json"
CHECKLIST_HTML = "checklist.html"
TASK_REPORT_HTML = "report.html"

RESULT_OK = "OK"
RESULT_NG = "NG"
RESULT_PARTIAL = "PARTIAL"
RESULT_BLOCKED = "BLOCKED"
RESULT_NOT_RUN = "NOT_RUN"
CASE_RESULTS = (RESULT_OK, RESULT_NG, RESULT_PARTIAL, RESULT_BLOCKED, RESULT_NOT_RUN)

TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
# step01_..., step01a_..., step02-03_..., step02-03b_..., extra_... (one screenshot may prove several steps).
IMAGE_NAME_PATTERN = re.compile(r"^(?:step\d{2}(?:-\d{2})?[a-z]?|extra)_[a-z0-9][a-z0-9._-]*\.(?:png|jpe?g|webp)$")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
PLACEHOLDER_PATTERN = re.compile(r"\bTODO\b")


# --------------------------------------------------------------------------- locating the root and the task


def evidence_root(repo_root: Path, root_argument: str | None) -> Path:
    """Evidence root: --root, then .devskills.toml [evidence].root, then an existing candidate, else `evidence/`."""
    if root_argument:
        return (repo_root / root_argument).resolve() if not Path(root_argument).is_absolute() else Path(root_argument)
    configured = _configured_root(repo_root)
    if configured:
        return (repo_root / configured).resolve()
    for candidate in ROOT_CANDIDATES:
        if (repo_root / candidate).is_dir():
            return (repo_root / candidate).resolve()
    return (repo_root / ROOT_CANDIDATES[0]).resolve()


def _configured_root(repo_root: Path) -> str | None:
    from devskills.profile import load_profile

    profile, _warnings = load_profile(repo_root)
    return profile.get("evidence", {}).get("root") or None


def task_dir_for(root: Path, task: str) -> Path:
    if not TASK_ID_PATTERN.match(task):
        raise UsageError(f"task id {task!r}: use letters, digits, '.', '_' or '-' (e.g. no63_5)")
    return root / task


def ensure_gitignored(repo_root: Path, root: Path) -> str:
    """Add the evidence root to the repository's .gitignore unless git already ignores it.

    Screenshots can show personal or customer data, so evidence never goes into the repository.
    Returns a short description of what happened.
    """
    try:
        relative = root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return "outside the repository: nothing to ignore"
    probe = f"{relative}/.devskills-ignore-probe"
    if run_git(repo_root, ["check-ignore", "-q", probe]) is not None:
        return f"already ignored by git: {relative}/"
    gitignore = repo_root / ".gitignore"
    current = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    entry = f"/{relative}/"
    if entry in current.splitlines():
        return f"already listed in .gitignore: {entry}"
    separator = "" if not current or current.endswith("\n") else "\n"
    addition = f"{separator}\n# E2E / manual test evidence (screenshots may contain personal data)\n{entry}\n"
    atomic_write_text(gitignore, current + addition)
    return f"added {entry} to .gitignore"


# --------------------------------------------------------------------------- checklist.json


def _text_value(value: Any, path: str, problems: list[str], required: bool = True) -> None:
    """A text is a string (same in every language) or {vi, en, ja}; placeholders are rejected."""
    if value is None or value == "":
        if required:
            problems.append(f"{path}: required")
        return
    if isinstance(value, str):
        if PLACEHOLDER_PATTERN.search(value):
            problems.append(f"{path}: still contains TODO")
        return
    if not isinstance(value, dict):
        problems.append(f"{path}: must be a string or an object with vi/en/ja")
        return
    for language in LANGUAGES:
        text = value.get(language)
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{path}.{language}: missing translation")
        elif PLACEHOLDER_PATTERN.search(text):
            problems.append(f"{path}.{language}: still contains TODO")


def _text_list(values: Any, path: str, problems: list[str]) -> None:
    if values is None:
        return
    if not isinstance(values, list):
        problems.append(f"{path}: must be a list")
        return
    for index, value in enumerate(values):
        _text_value(value, f"{path}[{index}]", problems)


def validate_checklist(data: Any) -> list[str]:
    """Return every problem in a checklist document (empty list = valid)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["checklist.json must be a JSON object"]
    if data.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}")
    task = data.get("task")
    if not isinstance(task, str) or not TASK_ID_PATTERN.match(task):
        problems.append("task: required, letters/digits/._- only")
        task = ""
    _text_value(data.get("title"), "title", problems)
    _text_value(data.get("summary"), "summary", problems, required=False)
    _text_list(data.get("preparation"), "preparation", problems)
    _text_value(data.get("rules"), "rules", problems, required=False)
    page_size = data.get("page_size", DEFAULT_PAGE_SIZE)
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100:
        problems.append("page_size: integer 1-100")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        problems.append("cases: at least one case is required")
        return problems
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        _validate_case(case, index, task, seen_ids, problems)
    return problems


def _validate_case(case: Any, index: int, task: str, seen_ids: set[str], problems: list[str]) -> None:
    """One case: id with the task prefix (unique), slug, texts, test data and steps with an expected result."""
    where = f"cases[{index}]"
    if not isinstance(case, dict):
        problems.append(f"{where}: must be an object")
        return
    case_id = case.get("id")
    if not isinstance(case_id, str) or not TASK_ID_PATTERN.match(case_id):
        problems.append(f"{where}.id: required, letters/digits/._- only")
    else:
        where = f"cases[{index}] {case_id}"
        if task and not case_id.lower().startswith(f"{task.lower()}-"):
            problems.append(f"{where}.id: must start with the task prefix '{task}-' (e.g. {task}-TC01)")
        if case_id.lower() in seen_ids:
            problems.append(f"{where}.id: duplicated")
        seen_ids.add(case_id.lower())
    slug = case.get("slug")
    if not isinstance(slug, str) or not SLUG_PATTERN.match(slug):
        problems.append(f"{where}.slug: lowercase a-z, 0-9, '-', e.g. edit-change-quantity")
    _text_value(case.get("title"), f"{where}.title", problems)
    _text_value(case.get("purpose"), f"{where}.purpose", problems)
    _text_list(case.get("preconditions"), f"{where}.preconditions", problems)
    _validate_case_data(case.get("data"), f"{where}.data", problems)
    _text_value(case.get("notes"), f"{where}.notes", problems, required=False)
    steps = case.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append(f"{where}.steps: at least one step is required")
        return
    has_expected = False
    for step_index, step in enumerate(steps):
        step_where = f"{where}.steps[{step_index}]"
        if not isinstance(step, dict):
            problems.append(f"{step_where}: must be an object")
            continue
        _text_value(step.get("action"), f"{step_where}.action", problems)
        _text_value(step.get("data"), f"{step_where}.data", problems, required=False)
        _text_value(step.get("expected"), f"{step_where}.expected", problems, required=False)
        expected_block = step.get("expected_block")
        if expected_block is not None and not isinstance(expected_block, str):
            problems.append(f"{step_where}.expected_block: must be a string (exact text shown on screen)")
        has_expected = has_expected or bool(step.get("expected") or expected_block)
    if not has_expected:
        problems.append(f"{where}: no step states an expected result")


def _validate_case_data(value: Any, path: str, problems: list[str]) -> None:
    """Test data: a list of {label, value} rows with concrete values."""
    if value is None:
        return
    if not isinstance(value, list):
        problems.append(f"{path}: must be a list of {{label, value}}")
        return
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            problems.append(f"{path}[{index}]: must be {{label, value}}")
            continue
        _text_value(row.get("label"), f"{path}[{index}].label", problems)
        _text_value(row.get("value"), f"{path}[{index}].value", problems)


def load_checklist(task_dir: Path) -> dict[str, Any]:
    """Read and validate <task>/checklist.json; raises UsageError listing the problems when it is missing or invalid."""
    path = task_dir / CHECKLIST_JSON
    if not path.is_file():
        raise UsageError(f"{path} not found: write the cases there first (see the e2e-evidence skill)")
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    problems = validate_checklist(data)
    if problems:
        listed = "\n  ".join(problems[:40])
        more = f"\n  ... {len(problems) - 40} more" if len(problems) > 40 else ""
        raise UsageError(f"{path} is not valid:\n  {listed}{more}")
    return data


def case_folder_name(case: dict[str, Any]) -> str:
    return f"{case['id']}_{case['slug']}"


def case_pages(cases: list[Any], page_size: int) -> list[int]:
    """1-based page number of each case."""
    return [index // page_size + 1 for index in range(len(cases))]


# --------------------------------------------------------------------------- HTML helpers


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def text_html(value: Any) -> str:
    """One language span per translation; a plain string is shown in every language."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return esc(value)
    return "".join(f'<span class="{language}">{esc(value.get(language, ""))}</span>' for language in LANGUAGES)


def heading_html(task: str, title: Any) -> str:
    """'<task> — <title>', without repeating the task id when every translation of the title already starts with it."""
    translations = [title] if isinstance(title, str) else [title.get(language, "") for language in LANGUAGES]
    if all(text.lower().startswith(task.lower()) for text in translations):
        return text_html(title)
    return f"{esc(task)} — {text_html(title)}"


def label_html(key: str) -> str:
    return text_html(UI_LABELS[key])


def page_shell(title: str, body: str, script: str, data_json: str = "", extra_style: str = "") -> str:
    """Complete self-contained HTML document: inline style, page body, optional embedded JSON data, inline script."""
    data_block = f'<script type="application/json" id="checklist-data">{data_json}</script>\n' if data_json else ""
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{PAGE_STYLE}{extra_style}</style>
</head>
<body data-lang="vi">
{body}
{data_block}<script>{script}</script>
</body>
</html>
"""


def toolbar_html(extra_buttons: str = "", with_cases: bool = True) -> str:
    """Language switch, progress and, on pages that list cases, the menu toggle and expand/collapse buttons."""
    languages = "".join(f'<button type="button" data-set-lang="{code}">{name}</button>'
                        for code, name in (("vi", "VN"), ("en", "EN"), ("ja", "日本語")))
    if not with_cases:
        return f'<div class="toolbar">{languages}<span class="sep"></span></div>'
    return (f'<div class="toolbar"><button type="button" class="menu-toggle" id="menuToggle">☰</button>{languages}'
            f'<span class="sep"></span><span class="progress" id="progress"></span>'
            f'<button type="button" id="expandAll">{label_html("expand_all")}</button>'
            f'<button type="button" id="collapseAll">{label_html("collapse_all")}</button>{extra_buttons}</div>')


def pager_html() -> str:
    return ('<nav class="pager" data-pager><button type="button" data-page-prev>‹</button>'
            '<span data-page-label></span><button type="button" data-page-next>›</button></nav>')


# --------------------------------------------------------------------------- checklist.html


def render_checklist(data: dict[str, Any]) -> str:
    """Self-contained checklist page in the plan.html look: hero with live stats, left menu, one card per case
    with preconditions, test data and step checkboxes, pages with totals, language switch."""
    task = data["task"]
    page_size = data.get("page_size", DEFAULT_PAGE_SIZE)
    cases = data["cases"]
    pages = case_pages(cases, page_size)
    menu_items = []
    blocks = []
    for number, (case, page) in enumerate(zip(cases, pages), start=1):
        case_id = case["id"]
        menu_items.append(
            f'<li data-page="{page}"><a href="#case-{esc(case_id)}" data-case-link="{esc(case_id)}" title="{esc(case_id)}">'
            f'<i class="dot" data-dot="{esc(case_id)}"></i><span class="mnum">{number:02d}</span>'
            f'<span>{text_html(case["title"])}</span></a></li>')
        blocks.append(_checklist_case_html(case, page, number))
    step_count = sum(len(case["steps"]) for case in cases)
    intro = []
    if data.get("preparation"):
        items = "".join(f"<li>{text_html(item)}</li>" for item in data["preparation"])
        intro.append(f'<details class="item depth-1" open><summary><span class="ititle">{label_html("preparation")}</span>'
                     f'</summary><div class="ibody"><div class="prose"><ol>{items}</ol></div></div></details>')
    if data.get("rules"):
        intro.append(f'<details class="item depth-1" open><summary><span class="ititle">{label_html("rules")}</span>'
                     f'</summary><div class="ibody"><div class="prose"><p>{text_html(data["rules"])}</p></div></div></details>')
    stats = _checklist_stats_html(len(cases), step_count)
    body = f"""<aside class="side" id="side">
  <div class="side-head"><span class="eyebrow">{esc(task)} · {label_html("checklist")}</span><b>{text_html(data["title"])}</b></div>
  <input type="search" class="search" id="caseSearch" placeholder="ID / keyword">
  <div class="side-totals" id="sideTotals"></div>
  <ul class="menu">{"".join(menu_items)}</ul>
</aside>
<main class="main plan checklist">
  {toolbar_html(f'<button type="button" id="resetChecks">{label_html("reset")}</button>')}
  <header class="hero">
    <div class="hero-top"><span class="eyebrow">{esc(task)} · {label_html("checklist")}</span>{_source_chips(data.get("source"))}</div>
    <h1>{heading_html(task, data["title"])}</h1>
    {f'<p class="lead">{text_html(data["summary"])}</p>' if data.get("summary") else ""}
    <div class="stats stats-5">{stats}</div>
    {_environment_html(data.get("environment"), data.get("source"))}
  </header>
  {"".join(intro)}
  <div class="page-totals" id="pageTotals"></div>
  {pager_html()}
  {"".join(blocks)}
  {pager_html()}
</main>"""
    data_json = json.dumps({"task": task, "page_size": page_size, "cases": [
        {"id": case["id"], "page": page, "steps": len(case["steps"])} for case, page in zip(cases, pages)]},
        ensure_ascii=False).replace("</", "<\\/")
    # The full checklist travels with its page: task-spec keeps no JSON file next to it (`spec source` reads it back).
    source = json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/")
    body += f'\n<script type="application/json" id="checklist-source">{source}</script>'
    return page_shell(f"{task} Checklist", body, CHECKLIST_SCRIPT, data_json, extra_style=PLAN_STYLE + CHECKLIST_STYLE)


def _checklist_stats_html(case_count: int, step_count: int) -> str:
    """Stat cards of the checklist hero; the script updates ticked steps, OK, NG and untested as the tester ticks."""
    cards = (
        (label_html("cases"), str(case_count), f"{step_count} step", "", ""),
        (label_html("steps_ticked"), f"0/{step_count}", "", "", ' id="statSteps"'),
        ("OK", "0", "", "st-ok", ' id="statOk"'),
        ("NG", "0", "", "st-ng", ' id="statNg"'),
        (label_html("untested"), str(case_count), "", "", ' id="statUntested"'),
    )
    return "".join(f'<div class="stat {css}"><span class="slabel">{label}</span><span class="svalue"{value_id}>{value}</span>'
                   f'<span class="snote">{note}</span></div>' for label, value, note, css, value_id in cards)


def _source_chips(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    return "".join(f'<span class="chip">{esc(key)}: {esc(source[key])}</span>'
                   for key in ("ticket", "branch", "base") if source.get(key) and not isinstance(source[key], list))


def _environment_html(environment: Any, source: Any) -> str:
    """Environment and reference documents under the hero (the documents the cases were derived from)."""
    rows = []
    if environment:
        rows.append(f'<div class="env-row"><b>{label_html("environment")}</b><span>{text_html(environment)}</span></div>')
    docs = source.get("docs") if isinstance(source, dict) else None
    if docs:
        shown = "".join(f"<code>{esc(item)}</code>" for item in (docs if isinstance(docs, list) else [docs]))
        rows.append(f'<div class="env-row"><b>docs</b><span class="doc-list">{shown}</span></div>')
    return f'<div class="env">{"".join(rows)}</div>' if rows else ""


def _checklist_case_html(case: dict[str, Any], page: int, number: int) -> str:
    """One case card: purpose, evidence folder, preconditions and test data side by side, steps, result."""
    case_id = case["id"]
    panels = []
    if case.get("preconditions"):
        items = "".join(f"<li>{text_html(item)}</li>" for item in case["preconditions"])
        panels.append(f'<section class="cl-panel"><h4>{label_html("preconditions")}</h4><ul>{items}</ul></section>')
    if case.get("data"):
        rows = "".join(f"<tr><th>{text_html(row['label'])}</th><td>{text_html(row['value'])}</td></tr>" for row in case["data"])
        panels.append(f'<section class="cl-panel"><h4>{label_html("test_data")}</h4>'
                      f'<table class="grid-table kv">{rows}</table></section>')
    step_rows = []
    for step_number, step in enumerate(case["steps"], start=1):
        expected = text_html(step.get("expected"))
        if step.get("expected_block"):
            expected += f"<pre>{esc(step['expected_block'])}</pre>"
        step_rows.append(
            f'<tr data-step-row><td class="n"><label><input type="checkbox" data-step="{esc(case_id)}-s{step_number}">'
            f'<span>{step_number:02d}</span></label></td><td>{text_html(step["action"])}</td>'
            f'<td>{text_html(step.get("data"))}</td><td class="exp">{expected}</td></tr>')
    parts = [f'<div class="case-meta"><span class="chip">{label_html("evidence_folder")}: '
             f'<code>{esc(case_folder_name(case))}/</code></span></div>']
    if panels:
        parts.append(f'<div class="cl-grid">{"".join(panels)}</div>')
    parts.append(f'<div class="table-wrap"><table class="grid-table steps"><tr><th>Step</th><th>{label_html("action")}</th>'
                 f'<th>{label_html("data")}</th><th>{label_html("expected")}</th></tr>{"".join(step_rows)}</table></div>')
    if case.get("notes"):
        parts.append(f'<div class="note">{text_html(case["notes"])}</div>')
    parts.append(
        f'<div class="res"><span class="res-label">{label_html("result")}</span>'
        f'<label class="toggle ok"><input type="checkbox" data-result="{esc(case_id)}" value="OK"><span>OK</span></label>'
        f'<label class="toggle ng"><input type="checkbox" data-result="{esc(case_id)}" value="NG"><span>NG</span></label>'
        f'<input type="text" class="memo" data-memo="{esc(case_id)}" placeholder="memo / screenshot"></div>')
    return (f'<details class="case block cl-case" id="case-{esc(case_id)}" data-page="{page}" data-case="{esc(case_id)}" open>'
            f'<summary><span class="bnum">{number:02d}</span><span class="btitle"><span class="cid">{esc(case_id)}</span> '
            f'{text_html(case["title"])}</span><i class="dot" data-dot="{esc(case_id)}"></i>'
            f'<span class="bcount" data-case-progress="{esc(case_id)}"></span></summary>'
            f'<p class="bhint">{text_html(case["purpose"])}</p><div class="bbody">{"".join(parts)}</div></details>')


# --------------------------------------------------------------------------- reading case results

STEP_PASS = "PASS"
STEP_NG = "NG"
STEP_NO_EVIDENCE = "NO_EVIDENCE"
STEP_NOT_RUN = "NOT_RUN"
# Worst first: when several summary rows describe one step, the worst status wins.
STEP_SEVERITY = {STEP_NG: 3, STEP_NO_EVIDENCE: 2, STEP_NOT_RUN: 1, STEP_PASS: 0}
# Overview order: what needs attention first.
RESULT_ORDER = (RESULT_NG, RESULT_BLOCKED, RESULT_PARTIAL, RESULT_NOT_RUN, RESULT_OK)
# Column names of the step table in summary_<case-id>.md (template in verify-and-summarize.md, plus Vietnamese).
STEP_TABLE_COLUMNS = {
    "step": ("step",),
    "action": ("checklist action", "checklist content", "action", "thao tác", "nội dung checklist"),
    "image": ("image", "images", "ảnh"),
    "observed": ("what the image shows", "observed", "quan sát", "quan sát trên ảnh", "thực tế"),
    "result": ("result", "kết quả"),
}
STEPS_SECTION_TITLES = ("steps", "step", "kết quả", "các step")
CONCLUSION_TITLES = ("conclusion", "kết luận", "結論")
IMAGE_NAME_IN_TEXT = re.compile(r"[\w.-]+\.(?:png|jpe?g|webp)", flags=re.IGNORECASE)
STEP_IMAGE_PREFIX = re.compile(r"^step(\d{2})(?:-(\d{2}))?[a-z]?_")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """`---` key: value lines `---` at the top of a summary; returns (fields, body)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, "\n".join(lines[index + 1:])
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip().lower()] = value.strip().strip('"').strip("'")
    return {}, text


def split_sections(body: str) -> list[tuple[str, str]]:
    """(title, text) per `## ` section; the part before the first one has the title ''. `# ` headings are dropped."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif not re.match(r"^# ", line):
            sections[-1][1].append(line)
    return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]


def normalize_step_status(text: str) -> str:
    """PASS / NG / NO_EVIDENCE / NOT_RUN from what a summary wrote ('**NG**', 'PASS (xem ghi chú 1)', 'NO EVIDENCE')."""
    cleaned = re.sub(r"[*`_]", " ", text).upper()
    if re.search(r"\bNG\b|\bFAIL", cleaned):
        return STEP_NG
    if re.search(r"NO\s*EVIDENCE|CHƯA CÓ ẢNH|THIẾU ẢNH", cleaned):
        return STEP_NO_EVIDENCE
    if re.search(r"NOT\s*RUN|CHƯA CHẠY|SKIP", cleaned):
        return STEP_NOT_RUN
    if re.search(r"\bPASS\b|\bOK\b|ĐẠT", cleaned):
        return STEP_PASS
    return STEP_NO_EVIDENCE


def _step_numbers(cell: str, previous: list[int]) -> list[int]:
    """'3' -> [3]; '2-3' -> [2, 3]; '(tiếp)' or '' -> the previous row's steps."""
    numbers = [int(number) for number in re.findall(r"\d+", cell)]
    if not numbers:
        return previous
    if len(numbers) == 2 and re.search(r"\d\s*[-–~]\s*\d", cell) and numbers[0] < numbers[1]:
        return list(range(numbers[0], numbers[1] + 1))
    return numbers[:1]


def _column_indexes(header_cells: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for position, cell in enumerate(header_cells):
        name = cell.strip().lower()
        for column, aliases in STEP_TABLE_COLUMNS.items():
            if column not in indexes and name in aliases:
                indexes[column] = position
    return indexes


def parse_step_table(text: str) -> dict[int, dict[str, Any]]:
    """Step number -> {status, observed[], images[], action} from the summary's step table."""
    steps: dict[int, dict[str, Any]] = {}
    indexes: dict[str, int] | None = None
    previous: list[int] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        if indexes is None:
            candidate = _column_indexes(cells)
            if "step" in candidate and "result" in candidate:
                indexes = candidate
            continue

        def cell(column: str) -> str:
            position = indexes.get(column)
            return cells[position] if position is not None and position < len(cells) else ""

        numbers = _step_numbers(cell("step"), previous)
        previous = numbers
        status = normalize_step_status(cell("result"))
        for number in numbers:
            step = steps.setdefault(number, {"status": STEP_PASS, "observed": [], "images": [], "action": ""})
            if STEP_SEVERITY[status] > STEP_SEVERITY[step["status"]]:
                step["status"] = status
            if cell("observed"):
                step["observed"].append(cell("observed"))
            step["images"] += [name for name in IMAGE_NAME_IN_TEXT.findall(cell("image")) if name not in step["images"]]
            step["action"] = step["action"] or cell("action")
    return steps


def _case_reason(result: str, fields: dict[str, str], steps: dict[int, dict[str, Any]], conclusion: str) -> str:
    """One line on why a case is not OK: front matter `reason:`, else the first failing step, else the conclusion."""
    if result == RESULT_OK:
        return ""
    if fields.get("reason"):
        return fields["reason"]
    for number in sorted(steps):
        step = steps[number]
        if step["status"] != STEP_PASS:
            observed = " / ".join(step["observed"]) or step["status"]
            return f"Step {number:02d} {step['status']}: {observed}"
    return conclusion.splitlines()[0] if conclusion else ""


def _read_summary_sections(body: str, entry: dict[str, Any]) -> None:
    """Fill entry steps (from the step table), conclusion and the other sections of a summary body."""
    for title, text in split_sections(body):
        lowered = title.lower()
        if lowered in STEPS_SECTION_TITLES or (not entry["steps"] and "|" in text and parse_step_table(text)):
            entry["steps"] = parse_step_table(text)
        elif lowered in CONCLUSION_TITLES:
            entry["conclusion"] = text
        else:
            entry["sections"].append((title, text))


def collect_case(task_dir: Path, folder: Path, case: dict[str, Any] | None, findings: list[Finding]) -> dict[str, Any]:
    """Result, steps, images and summary sections of one case folder; problems are appended to `findings`."""
    case_id = case["id"] if case else _case_id_of_unlisted_folder(folder)
    relative_folder = folder.relative_to(task_dir).as_posix()
    images = sorted(path.name for path in folder.iterdir()
                    if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES) if folder.is_dir() else []
    for name in images:
        if not IMAGE_NAME_PATTERN.match(name):
            findings.append(Finding("EVIDENCE-IMAGE-NAME", "low",
                                    f"{name}: rename to stepNN[a-z]_<what-is-shown>.png after checking which step it proves",
                                    path=f"{relative_folder}/{name}"))
    entry: dict[str, Any] = {"id": case_id, "folder": relative_folder, "images": images, "result": RESULT_NOT_RUN,
                             "summary_file": None, "fields": {}, "case": case, "steps": {}, "sections": [],
                             "conclusion": "", "reason": ""}
    summary_path = folder / f"summary_{case_id}.md"
    if not folder.is_dir():
        entry["reason"] = "no evidence folder"
        findings.append(Finding("EVIDENCE-CASE-NOT-RUN", "medium", f"{case_id}: no evidence folder {relative_folder}/",
                                path=relative_folder))
        return entry
    if not summary_path.is_file():
        entry["result"] = RESULT_NOT_RUN if not images else RESULT_BLOCKED
        entry["reason"] = f"summary_{case_id}.md missing: screenshots not verified"
        findings.append(Finding("EVIDENCE-SUMMARY-MISSING", "medium",
                                f"{case_id}: summary_{case_id}.md missing; screenshots are not verified yet",
                                path=relative_folder))
        return entry
    fields, body = parse_front_matter(summary_path.read_text(encoding="utf-8"))
    entry["summary_file"] = summary_path.relative_to(task_dir).as_posix()
    entry["fields"] = fields
    _read_summary_sections(body, entry)
    result = fields.get("result", "").upper()
    if result not in CASE_RESULTS:
        findings.append(Finding("EVIDENCE-RESULT-MISSING", "medium",
                                f"{case_id}: front matter needs result: {' | '.join(CASE_RESULTS)}",
                                path=entry["summary_file"]))
        result = RESULT_BLOCKED
    if result == RESULT_OK and not images:
        findings.append(Finding("EVIDENCE-OK-WITHOUT-IMAGES", "high",
                                f"{case_id}: marked OK but the folder has no screenshot", path=entry["summary_file"]))
        result = RESULT_PARTIAL
    for referenced in sorted(set(IMAGE_NAME_IN_TEXT.findall(body))):
        if referenced not in images:
            findings.append(Finding("EVIDENCE-IMAGE-MISSING", "medium",
                                    f"{case_id}: summary refers to {referenced}, which is not in the folder",
                                    path=entry["summary_file"]))
    unreferenced = [name for name in images if name not in body]
    if unreferenced:
        findings.append(Finding("EVIDENCE-IMAGE-UNREFERENCED", "low",
                                f"{case_id}: {len(unreferenced)} screenshot(s) not mentioned in the summary: "
                                f"{', '.join(unreferenced[:5])}", path=entry["summary_file"]))
    entry["result"] = result
    entry["reason"] = _case_reason(result, fields, entry["steps"], entry["conclusion"])
    return entry


def _case_id_of_unlisted_folder(folder: Path) -> str:
    """Case id of a folder that checklist.json does not list: from its summary_<id>.md, else the folder name.

    Task ids may contain '_' (no63_5), so the id is never split off the folder name.
    """
    summaries = sorted(folder.glob("summary_*.md")) if folder.is_dir() else []
    return summaries[0].stem[len("summary_"):] if summaries else folder.name


def _folder_of_case(case_id: str, folders: dict[str, Path]) -> str | None:
    """An existing folder named `<case-id>` or `<case-id>_<any slug>` (the slug may have been edited)."""
    wanted = case_id.lower()
    for name in folders:
        if name.lower() == wanted or name.lower().startswith(f"{wanted}_"):
            return name
    return None


def collect_task(task_dir: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[Finding]]:
    """(checklist or None, case entries in checklist order, folders outside the checklist, findings).

    Folders the checklist does not list (an older manual run, copies) are reported separately and never
    counted; without checklist.json every folder is read as a case.
    """
    findings: list[Finding] = []
    checklist: dict[str, Any] | None = None
    if (task_dir / CHECKLIST_JSON).is_file():
        checklist = load_checklist(task_dir)
    else:
        findings.append(Finding("EVIDENCE-CHECKLIST-MISSING", "medium",
                                f"{task_dir.name}: no checklist.json; the report shows the summaries without the "
                                "checklist steps (keep checklist.json with its run)", path=""))
    folders = {path.name: path for path in sorted(task_dir.iterdir()) if path.is_dir() and not path.name.startswith(".")}
    if not checklist:
        return None, [collect_case(task_dir, folder, None, findings) for folder in folders.values()], [], findings
    entries: list[dict[str, Any]] = []
    used: set[str] = set()
    for case in checklist["cases"]:
        name = case_folder_name(case)
        if name not in folders:
            name = _folder_of_case(case["id"], folders) or name
        used.add(name)
        entries.append(collect_case(task_dir, task_dir / name, case, findings))
    unlisted = []
    for name, folder in folders.items():
        if name in used:
            continue
        summaries = sorted(path.name for path in folder.glob("summary*.md"))
        image_count = sum(1 for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
        unlisted.append({"folder": name, "summary": summaries[0] if summaries else None, "images": image_count})
    return checklist, entries, unlisted, findings


def task_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {result: 0 for result in CASE_RESULTS}
    for entry in entries:
        counts[entry["result"]] += 1
    counts["cases"] = len(entries)
    counts["images"] = sum(len(entry["images"]) for entry in entries)
    return counts


def gate_for(counts: dict[str, int], findings: list[Finding]) -> str:
    """NG fails; anything not executed or not verified blocks; partial evidence warns; all OK passes."""
    if counts[RESULT_NG]:
        return GATE_FAIL
    if counts["cases"] == 0 or counts[RESULT_BLOCKED] or counts[RESULT_NOT_RUN] or any(
            finding.severity in ("high", "critical") for finding in findings):
        return GATE_BLOCKED
    if counts[RESULT_PARTIAL] or findings:
        return GATE_WARN
    return GATE_PASS


# --------------------------------------------------------------------------- minimal Markdown for summaries


def _inline_markdown(text: str) -> str:
    escaped = esc(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', escaped)


def _list_html(lines: list[str]) -> str:
    """A Markdown list with nesting by indentation (`  - child` under `- parent`); continuation lines join their item."""
    entries: list[tuple[int, bool, str]] = []  # (indent, ordered, text)
    for line in lines:
        item = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if item:
            entries.append((len(item.group(1)), item.group(2)[0].isdigit(), item.group(3)))
        elif entries:
            indent, ordered, text = entries[-1]
            entries[-1] = (indent, ordered, f"{text} {line.strip()}")

    def build(start: int, indent: int) -> tuple[str, int]:
        ordered = entries[start][1]
        items: list[str] = []
        position = start
        while position < len(entries) and entries[position][0] >= indent:
            if entries[position][0] == indent and entries[position][1] != ordered:
                break  # `- a` followed by `1. b` at the same level: two lists
            if entries[position][0] > indent:
                nested, position = build(position, entries[position][0])
                items[-1] = items[-1][:-len("</li>")] + nested + "</li>"
                continue
            items.append(f"<li>{_inline_markdown(entries[position][2])}</li>")
            position += 1
        tag = "ol" if ordered else "ul"
        return f"<{tag}>{''.join(items)}</{tag}>", position

    parts: list[str] = []
    position = 0
    while position < len(entries):
        part, position = build(position, entries[position][0])
        parts.append(part)
    return "".join(parts)


def markdown_html(text: str) -> str:
    """Headings, tables, lists, code fences, bold, inline code and links: what case summaries use."""
    output: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            output.append(f"<pre>{esc(chr(10).join(block))}</pre>")
            index += 1
            continue
        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
                    rows.append(cells)
                index += 1
            if rows:
                head = "".join(f"<th>{_inline_markdown(cell)}</th>" for cell in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{_inline_markdown(cell)}</td>" for cell in row) + "</tr>"
                               for row in rows[1:])
                output.append(f'<table class="md"><tr>{head}</tr>{body}</table>')
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)) + 2, 6)
            output.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            index += 1
            continue
        if re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped):
            block: list[str] = []
            while index < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[index])
                                          or (lines[index].startswith("  ") and lines[index].strip() and block)):
                block.append(lines[index])
                index += 1
            output.append(_list_html(block))
            continue
        if stripped:
            output.append(f"<p>{_inline_markdown(stripped)}</p>")
        index += 1
    return "\n".join(output)


# --------------------------------------------------------------------------- report.html (one file per task)


def file_href(*parts: str) -> str:
    """Relative link to a file or folder inside the task folder (spaces and non-ASCII names escaped)."""
    return esc("/".join(quote(part) for part in parts))


def _verdict(counts: dict[str, int]) -> str:
    if counts[RESULT_NG]:
        return RESULT_NG
    if counts["cases"] and counts[RESULT_OK] == counts["cases"]:
        return RESULT_OK
    if counts[RESULT_BLOCKED] or counts[RESULT_NOT_RUN] or not counts["cases"]:
        return "INCOMPLETE"
    return RESULT_PARTIAL


def _result_pill(result: str) -> str:
    return f'<span class="pill r-{result.lower()}">{esc(result.replace("_", " "))}</span>'


def _case_links(entry: dict[str, Any]) -> str:
    links = [f'<a href="#case-{esc(entry["id"])}" data-case-link="{esc(entry["id"])}">{label_html("details")}</a>',
             f'<a href="{file_href(entry["folder"])}/" target="_blank">{label_html("folder")}</a>']
    if entry["summary_file"]:
        links.append(f'<a href="{file_href(*entry["summary_file"].split("/"))}" target="_blank">summary.md</a>')
    return " · ".join(links)


def _overview_html(entries: list[dict[str, Any]]) -> str:
    """Every case in one table, grouped NG → BLOCKED → PARTIAL → NOT RUN → OK, with its reason and links."""
    rows = []
    for result in RESULT_ORDER:
        group = [entry for entry in entries if entry["result"] == result]
        if not group:
            continue
        rows.append(f'<tr class="group r-{result.lower()}"><th colspan="5">{_result_pill(result)} '
                    f'<span class="muted">{len(group)} {label_html("cases")}</span></th></tr>')
        for entry in group:
            case = entry["case"]
            title = text_html(case["title"]) if case else esc(entry["folder"])
            steps = entry["steps"]
            passed = sum(1 for step in steps.values() if step["status"] == STEP_PASS)
            total = len(case["steps"]) if case else len(steps)
            rows.append(
                f'<tr class="row"><td class="nowrap c-id"><span class="cid">{esc(entry["id"])}</span></td>'
                f'<td class="c-title">{title}</td><td class="nowrap num c-steps">{passed} / {total}</td>'
                f'<td class="c-reason">{_inline_markdown(entry["reason"]) or "—"}</td>'
                f'<td class="nowrap c-links">{_case_links(entry)}</td></tr>')
    head = (f'<tr class="head"><th>Case</th><th>{label_html("title")}</th><th>{label_html("steps_passed")}</th>'
            f'<th>{label_html("reason")}</th><th>{label_html("links")}</th></tr>')
    return (f'<details class="item depth-1 rp-overview" open><summary><span class="ititle">{label_html("overview")}'
            f'</span></summary><div class="ibody"><div class="table-wrap"><table class="grid-table">{head}{"".join(rows)}'
            f'</table></div></div></details>')


def _images_for_step(number: int, images: list[str]) -> list[str]:
    """Screenshots whose name says they prove this step: step03_, step03b_, step02-03_."""
    matched = []
    for name in images:
        prefix = STEP_IMAGE_PREFIX.match(name)
        if prefix:
            first = int(prefix.group(1))
            last = int(prefix.group(2)) if prefix.group(2) else first
            if first <= number <= last:
                matched.append(name)
    return matched


def _figures_html(folder: str, names: list[str]) -> str:
    figures = "".join(
        f'<figure><a href="{file_href(folder, name)}" target="_blank"><img loading="lazy" src="{file_href(folder, name)}" '
        f'alt="{esc(name)}"></a><figcaption>{esc(name)}</figcaption></figure>' for name in names)
    return f'<div class="shots">{figures}</div>' if figures else ""


def _step_block_html(number: int, step: dict[str, Any] | None, recorded: dict[str, Any] | None, images: list[str],
                     folder: str) -> str:
    """One step card: ticked box from the recorded result, action / data / expected, what was seen, its screenshots."""
    status = recorded["status"] if recorded else STEP_NOT_RUN
    checked = " checked" if status == STEP_PASS else ""
    rows = []
    action = text_html(step["action"]) if step else _inline_markdown(recorded["action"] if recorded else "")
    rows.append((label_html("action"), action))
    if step and step.get("data"):
        rows.append((label_html("data"), text_html(step["data"])))
    if step and (step.get("expected") or step.get("expected_block")):
        expected = text_html(step.get("expected"))
        if step.get("expected_block"):
            expected += f"<pre>{esc(step['expected_block'])}</pre>"
        rows.append((label_html("expected"), expected))
    observed = "".join(f"<div>{_inline_markdown(text)}</div>" for text in recorded["observed"]) if recorded else ""
    rows.append((label_html("observed"), observed or f'<span class="muted">{label_html("no_record")}</span>'))
    fields = "".join(f'<div class="kv-row{" observed" if index == len(rows) - 1 else ""}"><span class="k">{label}</span>'
                     f'<span class="v">{value}</span></div>' for index, (label, value) in enumerate(rows))
    return (f'<section class="rp-step s-{status.lower()}"><header><input type="checkbox" disabled{checked} aria-label="step">'
            f'<span class="snum">Step {number:02d}</span>{_result_pill(status)}</header><div class="kv">{fields}</div>'
            f'{_figures_html(folder, images)}</section>')


def _case_panels_html(case: dict[str, Any]) -> str:
    """Preconditions and test data side by side, as on the checklist."""
    panels = []
    if case.get("preconditions"):
        items = "".join(f"<li>{text_html(item)}</li>" for item in case["preconditions"])
        panels.append(f'<section class="cl-panel"><h4>{label_html("preconditions")}</h4><ul>{items}</ul></section>')
    if case.get("data"):
        rows = "".join(f"<tr><th>{text_html(row['label'])}</th><td>{text_html(row['value'])}</td></tr>" for row in case["data"])
        panels.append(f'<section class="cl-panel"><h4>{label_html("test_data")}</h4><table class="grid-table kv">{rows}</table></section>')
    return f'<div class="cl-grid">{"".join(panels)}</div>' if panels else ""


def _report_case_html(entry: dict[str, Any], page: int, number: int, case_findings: list[Finding]) -> str:
    """One case card: result, reason and conclusion, preconditions and data, a card per step with its screenshots."""
    case = entry["case"]
    result = entry["result"]
    folder = entry["folder"]
    title = text_html(case["title"]) if case else esc(folder)
    fields = entry["fields"]
    chips = [f'<span class="chip">{label_html(key)}: {esc(fields[key])}</span>'
             for key in ("environment", "tested_at", "tester") if fields.get(key)]
    parts = [f'<div class="case-meta">{"".join(chips)}<span class="links">{_case_links(entry)}</span></div>']
    if entry["reason"] and result != RESULT_OK:
        parts.append(f'<div class="reason r-{result.lower()}"><b>{label_html("reason")}</b>'
                     f'<span>{_inline_markdown(entry["reason"])}</span></div>')
    if entry["conclusion"]:
        parts.append(f'<div class="conclusion"><b>{label_html("conclusion")}</b><div class="prose">'
                     f'{markdown_html(entry["conclusion"])}</div></div>')
    if case:
        parts.append(_case_panels_html(case))
    shown: set[str] = set()
    step_numbers = range(1, len(case["steps"]) + 1) if case else sorted(entry["steps"])
    step_blocks = []
    for step_number in step_numbers:
        recorded = entry["steps"].get(step_number)
        named = [name for name in (recorded["images"] if recorded else []) if name in entry["images"]]
        images = named + [name for name in _images_for_step(step_number, entry["images"]) if name not in named]
        shown.update(images)
        step = case["steps"][step_number - 1] if case else None
        step_blocks.append(_step_block_html(step_number, step, recorded, images, folder))
    parts.append(f'<h4 class="rp-h">{label_html("steps")}</h4><div class="rp-steps">{"".join(step_blocks)}</div>')
    other_images = [name for name in entry["images"] if name not in shown]
    if other_images:
        parts.append(f'<h4 class="rp-h">{label_html("other_images")}</h4>{_figures_html(folder, other_images)}')
    for section_title, section_text in entry["sections"]:
        heading = esc(section_title) if section_title else label_html("summary_info")
        parts.append(f'<details class="item depth-2" open><summary><span class="ititle">{heading}</span></summary>'
                     f'<div class="ibody"><div class="prose">{markdown_html(section_text)}</div></div></details>')
    parts += [f'<div class="note">{esc(finding.message)}</div>' for finding in case_findings]
    purpose = f'<p class="bhint">{text_html(case["purpose"])}</p>' if case else ""
    return (f'<details class="case block rp-case r-{result.lower()}" id="case-{esc(entry["id"])}" data-page="{page}" '
            f'data-case="{esc(entry["id"])}" open><summary><span class="bnum">{number:02d}</span><span class="btitle">'
            f'<span class="cid">{esc(entry["id"])}</span> {title}</span>{_result_pill(result)}</summary>'
            f'{purpose}<div class="bbody">{"".join(parts)}</div></details>')


def _unlisted_html(unlisted: list[dict[str, Any]]) -> str:
    if not unlisted:
        return ""
    rows = "".join(
        f'<tr><td><a href="{file_href(item["folder"])}/" target="_blank">{esc(item["folder"])}/</a></td>'
        f'<td class="num">{item["images"]}</td><td>'
        + (f'<a href="{file_href(item["folder"], item["summary"])}" target="_blank">{esc(item["summary"])}</a>'
           if item["summary"] else "—")
        + "</td></tr>" for item in unlisted)
    return (f'<details class="item depth-1" open><summary><span class="ititle">{label_html("unlisted")}</span></summary>'
            f'<div class="ibody"><div class="table-wrap"><table class="grid-table"><tr><th>{label_html("folder")}</th>'
            f'<th>{label_html("images")}</th><th>summary</th></tr>{rows}</table></div></div></details>')


def _report_stats_html(counts: dict[str, int]) -> str:
    cards = [(esc(key.replace("_", " ")), counts[key], f"r-{key.lower()}") for key in RESULT_ORDER]
    cards.append((label_html("images"), counts["images"], ""))
    return "".join(f'<div class="stat {css}"><span class="slabel">{label}</span><span class="svalue">{value}</span>'
                   f'<span class="snote">/ {counts["cases"]} {label_html("cases")}</span></div>' if css else
                   f'<div class="stat"><span class="slabel">{label}</span><span class="svalue">{value}</span></div>'
                   for label, value, css in cards)


def render_task_report(task_dir: Path, checklist: dict[str, Any] | None, entries: list[dict[str, Any]],
                       unlisted: list[dict[str, Any]], findings: list[Finding]) -> str:
    """report.html in the plan / checklist look: verdict and stats, every case OK/NG with its reason and links,
    then a card per case with its steps, observations and screenshots. The only report file of a task."""
    task = checklist["task"] if checklist else task_dir.name
    title = checklist["title"] if checklist else ""
    page_size = checklist.get("page_size", DEFAULT_PAGE_SIZE) if checklist else DEFAULT_PAGE_SIZE
    pages = case_pages(entries, page_size)
    counts = task_counts(entries)
    verdict = _verdict(counts)
    findings_by_folder: dict[str, list[Finding]] = {}
    for finding in findings:
        findings_by_folder.setdefault((finding.path or "").split("/", 1)[0], []).append(finding)
    menu = []
    blocks = []
    for number, (entry, page) in enumerate(zip(entries, pages), start=1):
        case_title = text_html(entry["case"]["title"]) if entry["case"] else esc(entry["folder"])
        menu.append(f'<li data-page="{page}"><a href="#case-{esc(entry["id"])}" data-case-link="{esc(entry["id"])}" '
                    f'title="{esc(entry["id"])}"><i class="dot r-{entry["result"].lower()}"></i><span class="mnum">'
                    f'{number:02d}</span><span>{case_title}</span></a></li>')
        blocks.append(_report_case_html(entry, page, number, findings_by_folder.get(entry["folder"], [])))
    task_notes = "".join(f'<div class="note">{esc(finding.message)}</div>' for finding in findings if not finding.path)
    links = [f'<a href="{CHECKLIST_HTML}" target="_blank">{CHECKLIST_HTML}</a>'] if (task_dir / CHECKLIST_HTML).is_file() else []
    environment = next((entry["fields"]["environment"] for entry in entries if entry["fields"].get("environment")), "")
    env_block = (f'<div class="env"><div class="env-row"><b>{label_html("environment")}</b><span>{esc(environment)}</span>'
                 f'</div></div>') if environment else ""
    heading = heading_html(task, title) if title else esc(task)
    body = f"""<aside class="side" id="side">
  <div class="side-head"><span class="eyebrow">{esc(task)} · {label_html("report")}</span><b>{text_html(title) if title else esc(task)}</b></div>
  <input type="search" class="search" id="caseSearch" placeholder="ID / keyword">
  <ul class="menu">{"".join(menu)}</ul>
</aside>
<main class="main plan checklist report">
  {toolbar_html()}
  <header class="hero">
    <div class="hero-top"><span class="eyebrow">{esc(task)} · {label_html("report")}</span>
      {_source_chips((checklist or {}).get("source"))}<span class="verdict-pill r-{verdict.lower()}">{label_html("verdict")}: {verdict}</span></div>
    <h1>{heading}</h1>
    <div class="stats stats-6">{_report_stats_html(counts)}</div>
    {env_block}
    <div class="hero-links">{"".join(links)}<span class="muted">{label_html("generated")} {esc(utc_now_iso())}</span></div>
  </header>
  {task_notes}
  {_overview_html(entries)}
  <h2 class="rp-section">{label_html("case_details")}</h2>
  <div class="page-totals" id="pageTotals"></div>
  {pager_html()}
  {"".join(blocks)}
  {pager_html()}
  {_unlisted_html(unlisted)}
</main>"""
    data_json = json.dumps({"task": task, "page_size": page_size, "cases": [
        {"id": entry["id"], "page": page, "result": entry["result"]} for entry, page in zip(entries, pages)]},
        ensure_ascii=False).replace("</", "<\\/")
    return page_shell(f"{task} Report", body, REPORT_SCRIPT, data_json,
                      extra_style=PLAN_STYLE + CHECKLIST_STYLE + REPORT_STYLE)


# --------------------------------------------------------------------------- commands


def _repo_and_root(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = resolve_repo_root(getattr(args, "repo", None))
    return repo_root, evidence_root(repo_root, getattr(args, "root", None))


def cmd_init(args: argparse.Namespace) -> int:
    """Create <root>/<task>/ and make sure git ignores the evidence root."""
    repo_root, root = _repo_and_root(args)
    task_dir = task_dir_for(root, args.task)
    task_dir.mkdir(parents=True, exist_ok=True)
    ignore_note = ensure_gitignored(repo_root, root)
    lines = [f"evidence root: {root}", f"task folder:   {task_dir}", f"gitignore:     {ignore_note}"]
    checklist_path = task_dir / CHECKLIST_JSON
    if checklist_path.is_file():
        lines.append(f"checklist:     {checklist_path} exists; edit it, then `evidence checklist --task {args.task}`")
    else:
        lines.append(f"checklist:     write {checklist_path} (schema {SCHEMA}), then `evidence checklist --task {args.task}`")
    result = CheckResult(check_id=args.check_id, tool="devskills.evidence", execution_status=EXEC_COMPLETED,
                         gate_result=GATE_PASS, summary=f"task folder ready: {task_dir.name}",
                         details={"root": str(root), "task_dir": str(task_dir), "gitignore": ignore_note})
    return emit_result(args, repo_root, result, lines)


def _first_names(names: list[str], limit: int = 6) -> str:
    if not names:
        return ""
    more = " …" if len(names) > limit else ""
    return f" ({', '.join(names[:limit])}{more})"


def cmd_checklist(args: argparse.Namespace) -> int:
    """Validate checklist.json, write checklist.html and create one folder per case."""
    repo_root, root = _repo_and_root(args)
    task_dir = task_dir_for(root, args.task)
    data = load_checklist(task_dir)
    if data["task"] != args.task:
        raise UsageError(f"checklist.json task {data['task']!r} differs from --task {args.task!r}")
    atomic_write_text(task_dir / CHECKLIST_HTML, render_checklist(data))
    created = []
    for case in data["cases"]:
        folder = task_dir / case_folder_name(case)
        if not folder.exists():
            folder.mkdir(parents=True)
            created.append(folder.name)
    case_count = len(data["cases"])
    step_count = sum(len(case["steps"]) for case in data["cases"])
    page_count = max(case_pages(data["cases"], data.get("page_size", DEFAULT_PAGE_SIZE)) or [1])
    lines = [f"checklist: {task_dir / CHECKLIST_HTML}",
             f"cases: {case_count}, steps: {step_count}, pages: {page_count}",
             f"case folders created: {len(created)}" + _first_names(created)]
    result = CheckResult(check_id=args.check_id, tool="devskills.evidence", execution_status=EXEC_COMPLETED,
                         gate_result=GATE_PASS, summary=f"{case_count} case(s), {step_count} step(s)",
                         details={"task_dir": str(task_dir), "cases": case_count, "steps": step_count,
                                  "pages": page_count, "created_folders": created},
                         evidence_refs=[str(task_dir / CHECKLIST_HTML)])
    return emit_result(args, repo_root, result, lines)




def cmd_report(args: argparse.Namespace) -> int:
    """Write <task>/report.html for one task (--task) or for every task under the evidence root."""
    repo_root, root = _repo_and_root(args)
    if not root.is_dir():
        raise UsageError(f"evidence root {root} does not exist (run `evidence init --task <id>` first)")
    task_dirs = ([task_dir_for(root, args.task)] if args.task
                 else sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")))
    all_findings: list[Finding] = []
    totals = {result: 0 for result in CASE_RESULTS} | {"cases": 0, "images": 0}
    lines: list[str] = []
    for task_dir in task_dirs:
        if not task_dir.is_dir():
            raise UsageError(f"task folder {task_dir} does not exist")
        checklist, entries, unlisted, findings = collect_task(task_dir)
        report_path = task_dir / TASK_REPORT_HTML
        atomic_write_text(report_path, render_task_report(task_dir, checklist, entries, unlisted, findings))
        counts = task_counts(entries)
        for key in totals:
            totals[key] += counts[key]
        for finding in findings:
            finding.path = f"{task_dir.name}/{finding.path}" if finding.path else task_dir.name
        all_findings += findings
        lines.append(f"{task_dir.name}: {_verdict(counts)}  OK {counts[RESULT_OK]} · NG {counts[RESULT_NG]} · "
                     f"PARTIAL {counts[RESULT_PARTIAL]} · BLOCKED {counts[RESULT_BLOCKED]} · NOT_RUN "
                     f"{counts[RESULT_NOT_RUN]} · images {counts['images']}  -> {report_path}")
        for entry in entries:
            reason = f"  {entry['reason']}" if entry["reason"] and entry["result"] != RESULT_OK else ""
            lines.append(f"  {entry['result']:8} {entry['id']}{reason[:160]}")
        if unlisted:
            lines.append(f"  not in the checklist (not counted): {', '.join(item['folder'] for item in unlisted)}")
    lines += format_findings(all_findings)
    gate = gate_for(totals, all_findings)
    summary = (f"{totals['cases']} case(s): OK {totals[RESULT_OK]}, NG {totals[RESULT_NG]}, PARTIAL "
               f"{totals[RESULT_PARTIAL]}, BLOCKED {totals[RESULT_BLOCKED]}, NOT_RUN {totals[RESULT_NOT_RUN]}")
    result = CheckResult(check_id=args.check_id, tool="devskills.evidence", execution_status=EXEC_COMPLETED,
                         gate_result=gate, domain_result=_verdict(totals).lower(), summary=summary,
                         findings=all_findings, details={"root": str(root), "totals": totals},
                         evidence_refs=[str(task_dir / TASK_REPORT_HTML) for task_dir in task_dirs])
    return emit_result(args, repo_root, result, lines)
