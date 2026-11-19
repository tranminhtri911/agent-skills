"""Task specs from a requirement: `spec init`, `spec build` and `spec source`.

Layout under the specs root (committed with the project, one folder per ticket or task):

    <root>/<task>/require.md                  the original requirement, verbatim, plus one source line
    <root>/<task>/plan.html                   the plan: one block per page, small collapsible items, flow diagrams
    <root>/<task>/sub_tasks/taskNN_<slug>.md  one small task each: overview, implementation, unit test, E2E, verify
    <root>/<task>/checklist.html              test cases, the same page e2e-evidence uses

No JSON file is kept in the folder: the agent writes the plan and the checklist as JSON anywhere outside it
(a scratch file), `spec build --plan … --checklist …` validates and renders them, and each page embeds its own
data so `spec source` can print it again for the next edit.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from devskills.evidence import (
    CHECKLIST_HTML,
    LANGUAGES,
    PLACEHOLDER_PATTERN,
    SLUG_PATTERN,
    _text_value,
    esc,
    heading_html,
    label_html,
    markdown_html,
    page_shell,
    pager_html,
    render_checklist,
    split_sections,
    task_dir_for,
    text_html,
    toolbar_html,
    validate_checklist,
)
from devskills.evidence_templates import PLAN_SCRIPT, PLAN_STYLE, UI_LABELS
from devskills.flow_diagram import render_diagram, validate_diagram
from devskills.fsutil import atomic_write_text, read_json, resolve_repo_root, utc_now_iso
from devskills.models import (
    EXEC_COMPLETED,
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    CheckResult,
    Finding,
    UsageError,
    gate_from_findings,
)
from devskills.output import emit_result, format_findings

PLAN_SCHEMA = "devskills.task-plan/1"
REQUIRE_MD = "require.md"
PLAN_HTML = "plan.html"
SUB_TASKS_DIR = "sub_tasks"
PLAN_SOURCE_ID = "plan-source"
CHECKLIST_SOURCE_ID = "checklist-source"
ROOT_CANDIDATES = ("specs", "docs/specs", "spec")
SUBTASK_ID_PATTERN = re.compile(r"^task\d{2,3}$")
# Pages of plan.html in this order; "subtasks" is built from plan subtasks, the others are written blocks.
BLOCK_ORDER = ("overview", "current_flow", "target_flow", "changes", "impact", "subtasks", "verify", "test",
               "risks", "confirm", "estimate", "deploy")
REQUIRED_BLOCKS = tuple(block for block in BLOCK_ORDER if block != "subtasks")
FLOW_BLOCKS = ("current_flow", "target_flow")
CONFIRM_STATUSES = ("open", "answered", "n/a")
MAX_NESTING = 3
# Readability (SPEC-009): a reader must not scroll sideways through one sentence.
MAX_PROSE_LINE = 200
MAX_TABLE_CELL = 140
MAX_ITEM_LINES = 18
# Headings every sub task file needs (English or Vietnamese), matched case-insensitively at `## ` level.
SUBTASK_SECTIONS = {
    "overview": ("overview", "tổng quan"),
    "implementation": ("implementation", "cách triển khai", "triển khai"),
    "unit test": ("unit test", "test unit"),
    "e2e test": ("e2e test", "e2e", "test e2e"),
    "verify": ("verify", "kiểm chứng", "cách verify"),
}
REQUIRE_TEMPLATE = """# {task}

Nguồn:

<!-- Dán nguyên văn yêu cầu bên dưới. Không tóm tắt, không dịch, không thêm nội dung. -->
"""


# --------------------------------------------------------------------------- locating the root


def specs_root(repo_root: Path, root_argument: str | None) -> Path:
    """Specs root: --root, then .devskills.toml [spec].root, then an existing specs/ or docs/specs/, else specs/."""
    if root_argument:
        return (repo_root / root_argument).resolve() if not Path(root_argument).is_absolute() else Path(root_argument)
    from devskills.profile import load_profile

    profile, _warnings = load_profile(repo_root)
    configured = profile.get("spec", {}).get("root")
    if configured:
        return (repo_root / configured).resolve()
    for candidate in ROOT_CANDIDATES:
        if (repo_root / candidate).is_dir():
            return (repo_root / candidate).resolve()
    return (repo_root / ROOT_CANDIDATES[0]).resolve()


def require_text(task_dir: Path) -> str:
    """The pasted requirement: require.md without comments, headings and empty `Key:` lines."""
    path = task_dir / REQUIRE_MD
    if not path.is_file():
        return ""
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    meaningful = [line for line in text.splitlines()
                  if line.strip() and not line.startswith("#") and not re.fullmatch(r"\s*-?\s*[^:]{1,30}:\s*", line)]
    return "\n".join(meaningful).strip()


# --------------------------------------------------------------------------- embedded sources


def embed_json(script_id: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f'<script type="application/json" id="{script_id}">{payload}</script>'


def read_embedded(path: Path, script_id: str) -> Any | None:
    """The JSON a page embedded with `embed_json`, or None when the page or the block is missing."""
    if not path.is_file():
        return None
    match = re.search(rf'<script type="application/json" id="{script_id}">(.*?)</script>',
                      path.read_text(encoding="utf-8"), flags=re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(1).replace("<\\/", "</"))


def _read_json_argument(path_text: str, what: str) -> Any:
    path = Path(path_text).expanduser()
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise UsageError(f"cannot read the {what} JSON {path}: {error}") from error


# --------------------------------------------------------------------------- plan validation


def subtask_file_name(subtask: dict[str, Any]) -> str:
    return f"{subtask['id']}_{subtask['slug']}.md"


def _validate_item(item: Any, where: str, block_id: str, depth: int, problems: list[str]) -> bool:
    """One item: title, then a body, a diagram and/or child items. Returns whether it holds a diagram."""
    if not isinstance(item, dict):
        problems.append(f"{where}: must be an object")
        return False
    _text_value(item.get("title"), f"{where}.title", problems)
    children = item.get("items")
    has_content = bool(item.get("body") or item.get("diagram") or children)
    if not has_content:
        problems.append(f"{where}: needs a body, a diagram or child items")
    if item.get("body"):
        _text_value(item["body"], f"{where}.body", problems)
    has_diagram = False
    if item.get("diagram") is not None:
        problems += validate_diagram(item["diagram"], f"{where}.diagram")
        has_diagram = True
    if block_id == "confirm" and depth == 1 and item.get("status", "open") not in CONFIRM_STATUSES:
        problems.append(f"{where}.status: one of {', '.join(CONFIRM_STATUSES)}")
    if children is not None:
        if not isinstance(children, list) or not children:
            problems.append(f"{where}.items: a non-empty list of items")
        elif depth >= MAX_NESTING:
            problems.append(f"{where}.items: at most {MAX_NESTING} levels")
        else:
            for child_index, child in enumerate(children):
                has_diagram |= _validate_item(child, f"{where}.items[{child_index}]", block_id, depth + 1, problems)
    return has_diagram


def _validate_blocks(blocks: Any, problems: list[str]) -> None:
    if not isinstance(blocks, list) or not blocks:
        problems.append("blocks: list of {id, title?, items[]} required")
        return
    seen: set[str] = set()
    for index, block in enumerate(blocks):
        where = f"blocks[{index}]"
        if not isinstance(block, dict) or not isinstance(block.get("id"), str) or not SLUG_PATTERN.match(
                block["id"].replace("_", "-")):
            problems.append(f"{where}: needs an id such as overview, current_flow, changes")
            continue
        block_id = block["id"]
        where = f"blocks[{index}] {block_id}"
        if block_id in seen or block_id == "subtasks":
            problems.append(f"{where}: duplicated or reserved id (subtasks is built from `subtasks`)")
        seen.add(block_id)
        _text_value(block.get("title"), f"{where}.title", problems, required=block_id not in BLOCK_ORDER)
        if block.get("not_applicable"):
            _text_value(block["not_applicable"], f"{where}.not_applicable", problems)
            continue
        items = block.get("items")
        if not isinstance(items, list) or not items:
            problems.append(f"{where}.items: at least one item, or `not_applicable` with the reason")
            continue
        has_diagram = False
        for item_index, item in enumerate(items):
            has_diagram |= _validate_item(item, f"{where}.items[{item_index}]", block_id, 1, problems)
        if block_id in FLOW_BLOCKS and not has_diagram:
            problems.append(f"{where}: a flow needs at least one diagram {{nodes, edges}}")
    for block_id in REQUIRED_BLOCKS:
        if block_id not in seen:
            problems.append(f"blocks: `{block_id}` is missing")


def _validate_subtasks(subtasks: Any, problems: list[str]) -> None:
    if not isinstance(subtasks, list) or not subtasks:
        problems.append("subtasks: at least one {id, slug, title, estimate_hours} required")
        return
    ids = [item.get("id") for item in subtasks if isinstance(item, dict)]
    for index, subtask in enumerate(subtasks):
        where = f"subtasks[{index}]"
        if not isinstance(subtask, dict):
            problems.append(f"{where}: must be an object")
            continue
        if not isinstance(subtask.get("id"), str) or not SUBTASK_ID_PATTERN.match(subtask["id"]):
            problems.append(f"{where}.id: task01, task02, …")
        elif ids.count(subtask["id"]) > 1:
            problems.append(f"{where}.id: duplicated")
        if not isinstance(subtask.get("slug"), str) or not SLUG_PATTERN.match(subtask["slug"]):
            problems.append(f"{where}.slug: lowercase a-z, 0-9, '-'")
        _text_value(subtask.get("title"), f"{where}.title", problems)
        hours = subtask.get("estimate_hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
            problems.append(f"{where}.estimate_hours: positive number of hours")
        depends = subtask.get("depends_on", [])
        if not isinstance(depends, list) or any(dependency not in ids for dependency in depends):
            problems.append(f"{where}.depends_on: ids of other sub tasks")
        if subtask.get("status", "todo") not in ("todo", "done"):
            problems.append(f"{where}.status: todo or done")


def validate_plan(data: Any, task: str) -> list[str]:
    """Every problem in a plan (empty list = valid)."""
    if not isinstance(data, dict):
        return ["the plan must be a JSON object"]
    problems: list[str] = []
    if data.get("schema") != PLAN_SCHEMA:
        problems.append(f"schema must be {PLAN_SCHEMA!r}")
    if data.get("task") != task:
        problems.append(f"task must be {task!r} (the folder name)")
    _text_value(data.get("title"), "title", problems)
    _text_value(data.get("summary"), "summary", problems, required=False)
    _validate_blocks(data.get("blocks"), problems)
    _validate_subtasks(data.get("subtasks"), problems)
    return problems


def _raise_if_invalid(problems: list[str], what: str) -> None:
    if problems:
        listed = "\n  ".join(problems[:40])
        more = f"\n  … {len(problems) - 40} more" if len(problems) > 40 else ""
        raise UsageError(f"{what} is not valid:\n  {listed}{more}")


# --------------------------------------------------------------------------- readability and files


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value.get(language, "") for language in LANGUAGES]
    return []


def readability_findings(markdown: str, location: str) -> list[Finding]:
    """SPEC-009: no long one-line paragraphs or table cells, no wall of text in one item."""
    findings: list[Finding] = []
    in_code = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if stripped.startswith("|"):
            longest = max((len(cell.strip()) for cell in stripped.strip("|").split("|")), default=0)
            if longest > MAX_TABLE_CELL:
                findings.append(Finding("SPEC-LONG-LINE", "high", f"{location}: a table cell has {longest} characters "
                                        f"(max {MAX_TABLE_CELL}); split it into rows or a list", path=location))
                break
        elif len(stripped) > MAX_PROSE_LINE:
            findings.append(Finding("SPEC-LONG-LINE", "high", f"{location}: a line has {len(stripped)} characters "
                                    f"(max {MAX_PROSE_LINE}); one fact per line, use a list or sub items", path=location))
            break
    lines = [line for line in markdown.splitlines() if line.strip()]
    if len(lines) > MAX_ITEM_LINES:
        findings.append(Finding("SPEC-ITEM-TOO-LONG", "medium", f"{location}: {len(lines)} lines in one item "
                                f"(max {MAX_ITEM_LINES}); split it into child items", path=location))
    return findings


def _plan_readability(plan: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    def walk(items: list[dict[str, Any]], prefix: str) -> None:
        for number, item in enumerate(items, start=1):
            location = f"{prefix}.{number}"
            for text in _texts(item.get("body")):
                findings.extend(readability_findings(text, location))
            walk(item.get("items") or [], location)

    for block in plan["blocks"]:
        walk(block.get("items") or [], f"plan {block['id']}")
    return findings


def check_subtask_file(path: Path, relative: str) -> list[Finding]:
    """A sub task file must exist, carry the required sections, contain no TODO and stay readable."""
    if not path.is_file():
        return [Finding("SPEC-SUBTASK-MISSING", "high", f"{relative} is missing", path=relative)]
    text = path.read_text(encoding="utf-8")
    titles = {title.lower() for title, _ in split_sections(text) if title}
    findings = []
    for section, aliases in SUBTASK_SECTIONS.items():
        if not any(title.startswith(alias) for title in titles for alias in aliases):
            findings.append(Finding("SPEC-SUBTASK-SECTION", "high", f"{relative}: section `## {section.title()}` is missing",
                                    path=relative))
    if PLACEHOLDER_PATTERN.search(text):
        findings.append(Finding("SPEC-PLACEHOLDER", "medium", f"{relative} still contains TODO", path=relative))
    findings += [finding for finding in readability_findings(text, relative) if finding.rule_id == "SPEC-LONG-LINE"]
    return findings


def collect_findings(task_dir: Path, plan: dict[str, Any], checklist: dict[str, Any] | None) -> list[Finding]:
    """Findings for require.md, the plan's readability, the sub task files and the checklist."""
    findings: list[Finding] = []
    if not require_text(task_dir):
        findings.append(Finding("SPEC-REQUIRE-EMPTY", "high",
                                f"{REQUIRE_MD} has no requirement yet: paste the original request first", path=REQUIRE_MD))
    findings += _plan_readability(plan)
    for subtask in plan["subtasks"]:
        relative = f"{SUB_TASKS_DIR}/{subtask_file_name(subtask)}"
        findings += check_subtask_file(task_dir / relative, relative)
    listed = {subtask_file_name(subtask) for subtask in plan["subtasks"]}
    sub_dir = task_dir / SUB_TASKS_DIR
    for extra in sorted(path.name for path in sub_dir.glob("*.md")) if sub_dir.is_dir() else []:
        if extra not in listed:
            findings.append(Finding("SPEC-SUBTASK-UNLISTED", "low", f"{SUB_TASKS_DIR}/{extra} is not in the plan's subtasks",
                                    path=f"{SUB_TASKS_DIR}/{extra}"))
    if checklist is None:
        findings.append(Finding("SPEC-CHECKLIST-MISSING", "high",
                                "no checklist: pass --checklist <file> (e2e-evidence checklist schema)", path=CHECKLIST_HTML))
    for stray in ("plan.json", "checklist.json"):
        if (task_dir / stray).is_file():
            findings.append(Finding("SPEC-STRAY-JSON", "low", f"{stray} in the task folder is not used: the pages embed "
                                    "their data (`spec source`); delete it", path=stray))
    return findings


# --------------------------------------------------------------------------- plan.html


def _block_title(block_id: str, block: dict[str, Any] | None) -> str:
    if block and block.get("title"):
        return text_html(block["title"])
    key = f"block_{block_id}"
    return label_html(key) if key in UI_LABELS else esc(block_id)


def _ordered_blocks(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None]]:
    """Standard blocks in BLOCK_ORDER (subtasks built in), then any custom block in the order written."""
    written = {block["id"]: block for block in plan["blocks"]}
    ordered = [(block_id, written.get(block_id)) for block_id in BLOCK_ORDER]
    ordered += [(block["id"], block) for block in plan["blocks"] if block["id"] not in BLOCK_ORDER]
    return ordered


def _hours(value: float) -> str:
    return f"{value:g}h"


def _estimate_text(hours: float) -> str:
    """'8h ≈ 1.0 person-days' (8 working hours a day)."""
    return f"{_hours(hours)} ≈ {hours / 8:.1f} {label_html('days')}"


def _body_html(body: Any) -> str:
    if not body:
        return ""
    if isinstance(body, str):
        return f'<div class="prose">{markdown_html(body)}</div>'
    return "".join(f'<div class="prose {language}">{markdown_html(body.get(language, ""))}</div>' for language in LANGUAGES)


def _item_html(block_id: str, anchor: str, number: str, item: dict[str, Any], depth: int) -> str:
    """A collapsible item with its body, diagram and child items (nested up to MAX_NESTING)."""
    pills = ""
    if block_id == "confirm" and depth == 1:
        status = item.get("status", "open")
        pills += f' <span class="pill st-{esc(status.replace("/", ""))}">{esc(status.upper())}</span>'
    if item.get("owner"):
        pills += f' <span class="chip">{esc(item["owner"])}</span>'
    if item.get("tag"):
        pills += f' <span class="chip">{esc(item["tag"])}</span>'
    parts = [_body_html(item.get("body"))]
    if item.get("diagram"):
        title = item["title"] if isinstance(item["title"], str) else item["title"].get("en", "")
        parts.append(render_diagram(item["diagram"], title))
    for child_number, child in enumerate(item.get("items") or [], start=1):
        parts.append(_item_html(block_id, f"{anchor}-{child_number}", f"{number}.{child_number}", child, depth + 1))
    return (f'<details class="item depth-{depth}" id="{esc(anchor)}" open><summary><span class="inum">{esc(number)}</span>'
            f'<span class="ititle">{text_html(item["title"])}</span>{pills}</summary>'
            f'<div class="ibody">{"".join(parts)}</div></details>')


def _subtasks_html(task_dir: Path, plan: dict[str, Any]) -> str:
    """Table of sub tasks with estimate, status and dependencies, then each sub task file (collapsed)."""
    rows = []
    bodies = []
    for subtask in plan["subtasks"]:
        relative = f"{SUB_TASKS_DIR}/{subtask_file_name(subtask)}"
        depends = ", ".join(subtask.get("depends_on", [])) or "—"
        status = subtask.get("status", "todo")
        rows.append(f'<tr><td class="nowrap"><a href="#sub-{esc(subtask["id"])}" data-open-sub>{esc(subtask["id"])}</a></td>'
                    f'<td>{text_html(subtask["title"])}</td><td class="nowrap num">{_hours(subtask["estimate_hours"])}</td>'
                    f'<td class="nowrap"><span class="pill st-{status}" data-legend="task-{status}"></span></td>'
                    f'<td class="nowrap">{esc(depends)}</td><td class="nowrap"><a href="{esc(relative)}" target="_blank">'
                    f'{esc(relative)}</a></td></tr>')
        path = task_dir / relative
        content = markdown_html(path.read_text(encoding="utf-8")) if path.is_file() else (
            f'<div class="note">{esc(relative)} is missing</div>')
        bodies.append(f'<details class="item depth-1" id="sub-{esc(subtask["id"])}"><summary><span class="inum">'
                      f'{esc(subtask["id"])}</span><span class="ititle">{text_html(subtask["title"])}</span>'
                      f' <span class="chip">{_hours(subtask["estimate_hours"])}</span></summary>'
                      f'<div class="ibody"><div class="prose">{content}</div></div></details>')
    table = (f'<div class="table-wrap"><table class="grid-table"><tr><th>ID</th><th>{label_html("title_task")}</th>'
             f'<th>{label_html("estimate")}</th><th>{label_html("status")}</th><th>{label_html("depends_on")}</th>'
             f'<th>{label_html("file")}</th></tr>{"".join(rows)}</table></div>')
    return table + "".join(bodies)


def _estimate_table_html(plan: dict[str, Any]) -> str:
    total = sum(subtask["estimate_hours"] for subtask in plan["subtasks"])
    remaining = sum(subtask["estimate_hours"] for subtask in plan["subtasks"] if subtask.get("status") != "done")
    rows = "".join(f'<tr><td class="nowrap">{esc(subtask["id"])}</td><td>{text_html(subtask["title"])}</td>'
                   f'<td class="nowrap"><span class="pill st-{subtask.get("status", "todo")}" '
                   f'data-legend="task-{subtask.get("status", "todo")}"></span></td>'
                   f'<td class="nowrap num">{_hours(subtask["estimate_hours"])}</td></tr>' for subtask in plan["subtasks"])
    return (f'<div class="table-wrap"><table class="grid-table"><tr><th>ID</th><th>{label_html("title_task")}</th>'
            f'<th>{label_html("status")}</th><th>{label_html("estimate")}</th></tr>{rows}'
            f'<tr class="total"><th colspan="3">{label_html("total")}</th><th class="num">{_estimate_text(total)}</th></tr>'
            f'<tr class="total"><th colspan="3">{label_html("remaining")}</th><th class="num">{_estimate_text(remaining)}'
            f'</th></tr></table></div>')


def _checklist_summary_html(checklist: dict[str, Any] | None) -> str:
    if not checklist:
        return f'<div class="note">{CHECKLIST_HTML}: no checklist</div>'
    steps = sum(len(case["steps"]) for case in checklist["cases"])
    rows = "".join(f'<tr><td class="nowrap">{esc(case["id"])}</td><td>{text_html(case["title"])}</td>'
                   f'<td class="nowrap num">{len(case["steps"])}</td></tr>' for case in checklist["cases"])
    return (f'<p class="lead-link"><a href="{CHECKLIST_HTML}" target="_blank">{CHECKLIST_HTML}</a> · '
            f'{len(checklist["cases"])} {label_html("cases")} · {steps} step</p><div class="table-wrap">'
            f'<table class="grid-table"><tr><th>ID</th><th>{label_html("title_task")}</th><th>Step</th></tr>{rows}'
            f'</table></div>')


def _block_html(task_dir: Path, plan: dict[str, Any], checklist: dict[str, Any] | None, block_id: str,
                block: dict[str, Any] | None, page: int) -> str:
    parts = []
    if block_id == "subtasks":
        parts.append(_subtasks_html(task_dir, plan))
    if block_id == "estimate":
        parts.append(_estimate_table_html(plan))
    if block_id == "test":
        parts.append(_checklist_summary_html(checklist))
    if block and block.get("not_applicable"):
        parts.append(f'<div class="na"><b>{label_html("not_applicable")}:</b> {text_html(block["not_applicable"])}</div>')
    items = (block or {}).get("items") or []
    parts += [_item_html(block_id, f"item-{block_id}-{number}", str(number), item, 1)
              for number, item in enumerate(items, start=1)]
    count = len(plan["subtasks"]) if block_id == "subtasks" else len(items)
    hint_key = f"hint_{block_id}"
    hint = f'<p class="bhint">{label_html(hint_key)}</p>' if hint_key in UI_LABELS else ""
    return (f'<details class="case block" id="case-{esc(block_id)}" data-page="{page}" data-case="{esc(block_id)}" open>'
            f'<summary><span class="bnum">{page:02d}</span><span class="btitle">{_block_title(block_id, block)}</span>'
            f'<span class="bcount">{count}</span></summary>{hint}<div class="bbody">{"".join(parts)}</div></details>')


def _plan_menu_html(plan: dict[str, Any], ordered: list[tuple[str, dict[str, Any] | None]]) -> str:
    entries = []
    for page, (block_id, block) in enumerate(ordered, start=1):
        sub_items = ""
        if block:
            sub_items = "".join(f'<li class="sub" data-sub-page="{page}"><a href="#item-{esc(block_id)}-{number}" data-goto-page="{page}">'
                                f'{number}. {text_html(item["title"])}</a></li>'
                                for number, item in enumerate(block.get("items") or [], start=1))
        if block_id == "subtasks":
            sub_items = "".join(f'<li class="sub" data-sub-page="{page}"><a href="#sub-{esc(subtask["id"])}" data-goto-page="{page}" data-open-sub>'
                                f'{esc(subtask["id"])} {text_html(subtask["title"])}</a></li>' for subtask in plan["subtasks"])
        entries.append(f'<li data-page="{page}"><a href="#case-{esc(block_id)}" data-case-link="{esc(block_id)}">'
                       f'<span class="mnum">{page:02d}</span> {_block_title(block_id, block)}</a></li>{sub_items}')
    return f'<ul class="menu">{"".join(entries)}</ul>'


def _stats_html(plan: dict[str, Any], checklist: dict[str, Any] | None, open_questions: int, total_questions: int) -> str:
    total_hours = sum(subtask["estimate_hours"] for subtask in plan["subtasks"])
    done = sum(1 for subtask in plan["subtasks"] if subtask.get("status") == "done")
    cases = len(checklist["cases"]) if checklist else 0
    steps = sum(len(case["steps"]) for case in checklist["cases"]) if checklist else 0
    cards = [
        (label_html("estimate"), _hours(total_hours), f"≈ {total_hours / 8:.1f} {label_html('days')}", "estimate"),
        ("Sub task", str(len(plan["subtasks"])), f"{done} {label_html('done')}", "subtasks"),
        (label_html("open_questions"), str(open_questions), f"/ {total_questions}", "confirm"),
        (label_html("checklist"), str(cases), f"{steps} step", "test"),
    ]
    return "".join(f'<a class="stat" href="#case-{target}" data-case-link="{target}"><span class="slabel">{label}</span>'
                   f'<span class="svalue">{value}</span><span class="snote">{note}</span></a>'
                   for label, value, note, target in cards)


def render_plan(task_dir: Path, plan: dict[str, Any], checklist: dict[str, Any] | None) -> str:
    """plan.html: stats, one page per block with a step bar, collapsible items, diagrams; embeds the plan JSON."""
    task = plan["task"]
    ordered = _ordered_blocks(plan)
    confirm_block = next((block for block_id, block in ordered if block_id == "confirm"), None) or {}
    questions = confirm_block.get("items") or []
    open_questions = sum(1 for item in questions if item.get("status", "open") == "open")
    source = plan.get("source") or {}
    chips = "".join(f'<span class="chip">{esc(key)}: {esc(source[key])}</span>'
                    for key in ("ticket", "branch", "base") if source.get(key))
    links = (f'<a href="{REQUIRE_MD}" target="_blank">{label_html("requirement")}</a>'
             f'<a href="{CHECKLIST_HTML}" target="_blank">{CHECKLIST_HTML}</a>'
             f'<a href="{SUB_TASKS_DIR}/" target="_blank">{SUB_TASKS_DIR}/</a>')
    steps_bar = "".join(f'<a class="stepper-item" href="#case-{esc(block_id)}" data-case-link="{esc(block_id)}" '
                        f'data-step-page="{page}"><span class="snum">{page:02d}</span>{_block_title(block_id, block)}</a>'
                        for page, (block_id, block) in enumerate(ordered, start=1))
    blocks = "".join(_block_html(task_dir, plan, checklist, block_id, block, page)
                     for page, (block_id, block) in enumerate(ordered, start=1))
    show_all = f'<button type="button" id="showAll">{label_html("show_all")}</button>'
    body = f"""<aside class="side" id="side">
  <div class="side-head"><span class="eyebrow">{esc(task)}</span><b>{text_html(plan["title"])}</b></div>
  <input type="search" class="search" id="caseSearch" placeholder="keyword">
  {_plan_menu_html(plan, ordered)}
</aside>
<main class="main plan">
  {toolbar_html(show_all)}
  <header class="hero">
    <div class="hero-top"><span class="eyebrow">{esc(task)}</span>{chips}</div>
    <h1>{heading_html(task, plan["title"])}</h1>
    {f'<p class="lead">{text_html(plan["summary"])}</p>' if plan.get("summary") else ""}
    <div class="stats">{_stats_html(plan, checklist, open_questions, len(questions))}</div>
    <div class="hero-links">{links}<span class="muted">{label_html("generated")} {esc(utc_now_iso())}</span></div>
  </header>
  <nav class="stepper" aria-label="pages">{steps_bar}</nav>
  {blocks}
  {pager_html()}
</main>
{embed_json(PLAN_SOURCE_ID, plan)}"""
    data_json = json.dumps({"task": task, "page_size": 1, "cases": [
        {"id": block_id, "page": page} for page, (block_id, _block) in enumerate(ordered, start=1)]},
        ensure_ascii=False).replace("</", "<\\/")
    return page_shell(f"{task} Plan", body, PLAN_SCRIPT, data_json, extra_style=PLAN_STYLE)


# --------------------------------------------------------------------------- commands


def _repo_and_root(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = resolve_repo_root(getattr(args, "repo", None))
    return repo_root, specs_root(repo_root, getattr(args, "root", None))


def cmd_init(args: argparse.Namespace) -> int:
    """Create <root>/<task>/ with a short require.md template and sub_tasks/; never overwrites an existing file."""
    repo_root, root = _repo_and_root(args)
    task_dir = task_dir_for(root, args.task)
    (task_dir / SUB_TASKS_DIR).mkdir(parents=True, exist_ok=True)
    require_path = task_dir / REQUIRE_MD
    created = not require_path.exists()
    if created:
        atomic_write_text(require_path, REQUIRE_TEMPLATE.format(task=args.task))
    has_requirement = bool(require_text(task_dir))
    lines = [f"specs root: {root}", f"task folder: {task_dir}",
             f"require.md: {'created' if created else 'kept'}{'' if has_requirement else ' — paste the requirement'}",
             "next: write the plan and checklist JSON outside the folder and sub_tasks/taskNN_<slug>.md, then "
             f"`spec build --task {args.task} --plan <file> --checklist <file>`"]
    result = CheckResult(check_id=args.check_id, tool="devskills.spec", execution_status=EXEC_COMPLETED,
                         gate_result=GATE_PASS if has_requirement else GATE_WARN,
                         summary=f"task folder ready: {task_dir.name}",
                         details={"root": str(root), "task_dir": str(task_dir), "require_created": created,
                                  "has_requirement": has_requirement})
    return emit_result(args, repo_root, result, lines)


def _load_sources(args: argparse.Namespace, task_dir: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The plan and checklist from --plan/--checklist, else the data embedded in the current pages."""
    plan = _read_json_argument(args.plan, "plan") if args.plan else read_embedded(task_dir / PLAN_HTML, PLAN_SOURCE_ID)
    if plan is None:
        raise UsageError(f"no plan: pass --plan <file> (plan.html of {task_dir.name} has no embedded plan yet)")
    _raise_if_invalid(validate_plan(plan, task_dir.name), "the plan")
    checklist = (_read_json_argument(args.checklist, "checklist") if args.checklist
                 else read_embedded(task_dir / CHECKLIST_HTML, CHECKLIST_SOURCE_ID))
    if checklist is not None:
        _raise_if_invalid(validate_checklist(checklist), "the checklist")
    return plan, checklist


def cmd_build(args: argparse.Namespace) -> int:
    """Validate the plan, sub task files and checklist; write plan.html and checklist.html with their data embedded."""
    repo_root, root = _repo_and_root(args)
    task_dir = task_dir_for(root, args.task)
    if not task_dir.is_dir():
        raise UsageError(f"task folder {task_dir} does not exist (run `spec init --task {args.task}` first)")
    plan, checklist = _load_sources(args, task_dir)
    findings = collect_findings(task_dir, plan, checklist)
    atomic_write_text(task_dir / PLAN_HTML, render_plan(task_dir, plan, checklist))
    written = [str(task_dir / PLAN_HTML)]
    if checklist:
        atomic_write_text(task_dir / CHECKLIST_HTML, render_checklist(checklist))
        written.append(str(task_dir / CHECKLIST_HTML))
    total_hours = sum(subtask["estimate_hours"] for subtask in plan["subtasks"])
    lines = [f"plan: {task_dir / PLAN_HTML}",
             f"blocks: {len(plan['blocks'])} + subtasks · sub tasks: {len(plan['subtasks'])} · estimate {_hours(total_hours)}",
             f"checklist: {task_dir / CHECKLIST_HTML if checklist else 'missing'}"
             + (f" ({len(checklist['cases'])} cases)" if checklist else "")]
    lines += format_findings(findings)
    gate = gate_from_findings(findings, "high")
    result = CheckResult(check_id=args.check_id, tool="devskills.spec", execution_status=EXEC_COMPLETED,
                         gate_result=gate, summary=f"{len(plan['subtasks'])} sub task(s), {_hours(total_hours)}"
                         + (", problems found" if gate == GATE_FAIL else ""),
                         findings=findings, details={"task_dir": str(task_dir), "estimate_hours": total_hours,
                                                     "subtasks": len(plan["subtasks"])},
                         evidence_refs=written)
    return emit_result(args, repo_root, result, lines)


def cmd_source(args: argparse.Namespace) -> int:
    """Print (or write to --out) the plan or checklist JSON embedded in the task's page, to edit and rebuild."""
    _repo_root, root = _repo_and_root(args)
    task_dir = task_dir_for(root, args.task)
    page, script_id = (PLAN_HTML, PLAN_SOURCE_ID) if args.part == "plan" else (CHECKLIST_HTML, CHECKLIST_SOURCE_ID)
    data = read_embedded(task_dir / page, script_id)
    if data is None:
        raise UsageError(f"{task_dir / page} has no embedded {args.part} (build it with `spec build` first)")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        atomic_write_text(Path(args.out).expanduser(), text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0
