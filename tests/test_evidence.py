"""`ds.py evidence`: task folder + .gitignore, checklist validation/rendering, case results and reports."""

from __future__ import annotations

import copy
import json
import unittest

from devskills import evidence
from tests._support import REPO_ROOT, commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write

EXAMPLE = json.loads((REPO_ROOT / "skills/e2e-evidence/assets/checklist.example.json").read_text(encoding="utf-8"))
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201a35d1d7b0000000049454e44ae426082")


def summary(case_id: str, result: str, body: str) -> str:
    return f"---\ncase: {case_id}\nresult: {result}\nsteps_passed: 1\nsteps_total: 1\n---\n{body}\n"


class ChecklistValidationTest(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(evidence.validate_checklist(EXAMPLE), [])

    def test_case_id_needs_task_prefix_and_translations(self):
        data = copy.deepcopy(EXAMPLE)
        data["cases"][0]["id"] = "TC01"
        data["cases"][1]["title"] = {"vi": "chỉ tiếng Việt"}
        data["cases"][1]["steps"][0]["action"] = "TODO"
        problems = "\n".join(evidence.validate_checklist(data))
        self.assertIn("task prefix 'demo42-'", problems)
        self.assertIn("title.en: missing translation", problems)
        self.assertIn("still contains TODO", problems)

    def test_case_without_expected_result_is_rejected(self):
        data = copy.deepcopy(EXAMPLE)
        for step in data["cases"][1]["steps"]:
            step.pop("expected", None)
            step.pop("expected_block", None)
        self.assertTrue(any("no step states an expected result" in item for item in evidence.validate_checklist(data)))

    def test_heading_does_not_repeat_the_task_id(self):
        self.assertEqual(evidence.heading_html("no63_5", "No63_5 — memo"), "No63_5 — memo")
        self.assertIn("demo42 — ", evidence.heading_html("demo42", EXAMPLE["title"]))

    def test_pages_split_by_page_size(self):
        self.assertEqual(evidence.case_pages(list(range(23)), 10), [1] * 10 + [2] * 10 + [3] * 3)


class EvidenceCommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_dir(self)
        init_git_repo(self.repo)
        write(self.repo, "README.md", "demo\n")
        commit_all(self.repo)

    def init_and_render(self, data=None) -> None:
        self.assertEqual(run_cli("evidence", "init", "--task", "demo42", cwd=self.repo).returncode, 0)
        write(self.repo, "evidence/demo42/checklist.json", json.dumps(data or EXAMPLE, ensure_ascii=False))
        completed = run_cli("evidence", "checklist", "--task", "demo42", cwd=self.repo)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_init_adds_gitignore_once_and_uses_existing_root(self):
        (self.repo / "deploy/evidence").mkdir(parents=True)
        run_cli("evidence", "init", "--task", "t1", cwd=self.repo)
        run_cli("evidence", "init", "--task", "t2", cwd=self.repo)
        gitignore = (self.repo / ".gitignore").read_text()
        self.assertEqual(gitignore.count("/deploy/evidence/"), 1)
        self.assertTrue((self.repo / "deploy/evidence/t2").is_dir())

    def test_checklist_renders_three_languages_menu_and_case_folders(self):
        self.init_and_render()
        task_dir = self.repo / "evidence/demo42"
        page = (task_dir / "checklist.html").read_text()
        for marker in ('data-set-lang="ja"', 'class="side"', 'data-step="demo42-TC01-s2"', 'data-result="demo42-TC02"',
                       "<pre>・DEMO Projector(1,100円)×1", 'id="pageTotals"', '<span class="ja">'):
            self.assertIn(marker, page)
        self.assertTrue((task_dir / "demo42-TC01_create-allday-qty3").is_dir())
        self.assertTrue((task_dir / "demo42-TC02_short-time-no-allday").is_dir())

    def test_invalid_checklist_is_a_usage_error(self):
        data = copy.deepcopy(EXAMPLE)
        data["cases"][0]["slug"] = "Bad Slug"
        run_cli("evidence", "init", "--task", "demo42", cwd=self.repo)
        write(self.repo, "evidence/demo42/checklist.json", json.dumps(data))
        completed = run_cli("evidence", "checklist", "--task", "demo42", cwd=self.repo)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("slug", completed.stderr)

    def test_report_without_summaries_is_blocked(self):
        self.init_and_render()
        code, payload = run_cli_json("evidence", "report", "--task", "demo42", cwd=self.repo)
        self.assertEqual(code, 4)
        self.assertEqual(payload["details"]["totals"]["NOT_RUN"], 2)
        self.assertTrue((self.repo / "evidence/demo42/report.html").is_file())
        self.assertFalse((self.repo / "evidence/demo42/checklist_report.html").exists())
        self.assertFalse((self.repo / "evidence/report.html").exists())

    def test_all_ok_passes_and_report_shows_images(self):
        self.init_and_render()
        task_dir = self.repo / "evidence/demo42"
        for folder, case_id in (("demo42-TC01_create-allday-qty3", "demo42-TC01"),
                                ("demo42-TC02_short-time-no-allday", "demo42-TC02")):
            write(task_dir, f"{folder}/step01_memo-lines.png", PNG_1PX)
            write(task_dir, f"{folder}/summary_{case_id}.md", summary(case_id, "OK", "| 1 | `step01_memo-lines.png` | PASS |"))
        code, payload = run_cli_json("evidence", "report", "--task", "demo42", cwd=self.repo)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["details"]["totals"]["OK"], 2)
        report = (task_dir / "report.html").read_text()
        self.assertIn('src="demo42-TC01_create-allday-qty3/step01_memo-lines.png"', report)
        self.assertIn("r-ok", report)

    def test_ng_fails_and_ok_without_image_is_downgraded(self):
        self.init_and_render()
        task_dir = self.repo / "evidence/demo42"
        write(task_dir, "demo42-TC01_create-allday-qty3/summary_demo42-TC01.md", summary("demo42-TC01", "OK", "no image"))
        write(task_dir, "demo42-TC02_short-time-no-allday/step01_memo.png", PNG_1PX)
        write(task_dir, "demo42-TC02_short-time-no-allday/summary_demo42-TC02.md",
              summary("demo42-TC02", "NG", "`step01_memo.png` shows (1,100円)×1"))
        code, payload = run_cli_json("evidence", "report", "--task", "demo42", cwd=self.repo)
        self.assertEqual(code, 3)
        rules = {finding["rule_id"] for finding in payload["findings"]}
        self.assertIn("EVIDENCE-OK-WITHOUT-IMAGES", rules)
        self.assertEqual(payload["details"]["totals"]["PARTIAL"], 1)
        self.assertEqual(payload["details"]["totals"]["NG"], 1)

    def test_unnamed_and_missing_images_are_reported(self):
        self.init_and_render()
        task_dir = self.repo / "evidence/demo42"
        folder = "demo42-TC01_create-allday-qty3"
        write(task_dir, f"{folder}/Screenshot 2026-11-18.png", PNG_1PX)
        write(task_dir, f"{folder}/summary_demo42-TC01.md", summary("demo42-TC01", "PARTIAL", "`step02_missing.png`"))
        _, payload = run_cli_json("evidence", "report", "--task", "demo42", cwd=self.repo)
        rules = {finding["rule_id"] for finding in payload["findings"]}
        self.assertTrue({"EVIDENCE-IMAGE-NAME", "EVIDENCE-IMAGE-MISSING", "EVIDENCE-IMAGE-UNREFERENCED"} <= rules)

    def test_task_id_with_underscore_matches_its_case_folders(self):
        data = copy.deepcopy(EXAMPLE)
        data["task"] = "no63_5"
        for number, case in enumerate(data["cases"], start=1):
            case["id"] = f"no63_5-TC{number:02d}"
        self.assertEqual(run_cli("evidence", "init", "--task", "no63_5", cwd=self.repo).returncode, 0)
        write(self.repo, "evidence/no63_5/checklist.json", json.dumps(data, ensure_ascii=False))
        self.assertEqual(run_cli("evidence", "checklist", "--task", "no63_5", cwd=self.repo).returncode, 0)
        task_dir = self.repo / "evidence/no63_5"
        write(task_dir, "no63_5-TC01_create-allday-qty3/step01_a.png", PNG_1PX)
        write(task_dir, "no63_5-TC01_create-allday-qty3/summary_no63_5-TC01.md",
              summary("no63_5-TC01", "NG", "`step01_a.png` differs"))
        _, payload = run_cli_json("evidence", "report", "--task", "no63_5", cwd=self.repo)
        self.assertEqual(payload["details"]["totals"]["NG"], 1)
        self.assertNotIn("EVIDENCE-FOLDER-UNKNOWN", {finding["rule_id"] for finding in payload["findings"]})
        self.assertIn("differs", (task_dir / "report.html").read_text())


    def test_report_lists_every_case_with_reason_and_shows_each_step(self):
        self.init_and_render()
        task_dir = self.repo / "evidence/demo42"
        tc01 = "demo42-TC01_create-allday-qty3"
        for name in ("step01_room-a.png", "step02_memo-lines.png", "step03_pdf.png", "extra_detail.png"):
            write(task_dir, f"{tc01}/{name}", PNG_1PX)
        write(task_dir, f"{tc01}/summary_demo42-TC01.md", (
            "---\ncase: demo42-TC01\nresult: NG\nsteps_passed: 2\nsteps_total: 3\n---\n# demo42-TC01\n\n## Steps\n\n"
            "| Step | Checklist action | Image | What the image shows | Result |\n|---|---|---|---|---|\n"
            "| 1 | open form | `step01_room-a.png` | all-day label | PASS |\n"
            "| 2 | add projector | `step02_memo-lines.png` | (1,100円)×1 / (550円)×2 | PASS |\n"
            "| 3 | save, PDF | `step03_pdf.png` | PDF shows 3,300 instead of 2,200 | **NG** |\n\n"
            "## Notes\n\n- `extra_detail.png` shows the detail screen.\n\n## Conclusion\n\n2 / 3 PASS. Result: NG.\n"))
        write(task_dir, "TC9_old-manual-run/summary.md", "old manual notes")
        code, payload = run_cli_json("evidence", "report", "--task", "demo42", cwd=self.repo)
        self.assertEqual(code, 3)
        self.assertEqual(payload["details"]["totals"]["cases"], 2, "a folder outside the checklist is not a case")
        report = (task_dir / "report.html").read_text()
        overview = report.split('rp-overview', 1)[1].split("</table>", 1)[0]
        self.assertIn("Step 03 NG: PDF shows 3,300 instead of 2,200", overview)
        self.assertLess(overview.index("demo42-TC01"), overview.index("demo42-TC02"), "NG is listed before NOT RUN")
        self.assertIn('href="demo42-TC01_create-allday-qty3/summary_demo42-TC01.md"', overview)
        step3 = report.split('<span class="snum">Step 03</span>', 1)[1].split("</section>", 1)[0]
        self.assertIn('src="demo42-TC01_create-allday-qty3/step03_pdf.png"', step3)
        self.assertIn("2,200", step3, "the expected result of the checklist step is shown")
        self.assertIn('<input type="checkbox" disabled checked aria-label="step"><span class="snum">Step 01</span>', report)
        other_images = report.split('<h4 class="rp-h">', 2)[-1]
        self.assertIn('src="demo42-TC01_create-allday-qty3/extra_detail.png"', other_images,
                      "screenshots of no step are shown under other screenshots")
        self.assertIn('class="verdict-pill r-ng"', report)
        self.assertIn("TC9_old-manual-run/", report)

    def test_moved_task_folder_keeps_matching_cases_by_id(self):
        self.init_and_render()
        moved = self.repo / "evidence/demo42_copy"
        (self.repo / "evidence/demo42").rename(moved)
        write(moved, "demo42-TC02_short-time-no-allday/step01_memo.png", PNG_1PX)
        write(moved, "demo42-TC02_short-time-no-allday/summary_demo42-TC02.md",
              summary("demo42-TC02", "OK", "| Step | Image | What the image shows | Result |\n|---|---|---|---|\n"
                                           "| 1 | `step01_memo.png` | (550円)×3 | PASS |"))
        _, payload = run_cli_json("evidence", "report", "--task", "demo42_copy", cwd=self.repo)
        self.assertEqual(payload["details"]["totals"]["OK"], 1)
        self.assertEqual(payload["details"]["totals"]["NOT_RUN"], 1)


class StepTableTest(unittest.TestCase):
    def test_ranges_continuations_and_worst_status(self):
        steps = evidence.parse_step_table(
            "| Step | Checklist action | Image | What the image shows | Result |\n|---|---|---|---|---|\n"
            "| 2-3 | both | `step02-03_form.png` | form | PASS |\n| 3 | memo | `step03b_memo.png` | wrong | **NG** |\n"
            "| 4 | pdf | `step04a_pdf.png` | top | PASS |\n| (tiếp) | pdf | | no total visible | NO EVIDENCE |\n")
        self.assertEqual(steps[2]["status"], "PASS")
        self.assertEqual(steps[3]["status"], "NG")
        self.assertEqual(steps[3]["images"], ["step02-03_form.png", "step03b_memo.png"])
        self.assertEqual(steps[4]["status"], "NO_EVIDENCE", "a continuation row belongs to the previous step")
        self.assertEqual(steps[4]["observed"], ["top", "no total visible"])


class MarkdownTest(unittest.TestCase):
    def test_tables_lists_and_escaping(self):
        rendered = evidence.markdown_html("# T\n\n| a | b |\n|---|---|\n| `x` | <b>y</b> |\n\n- one\n- **two**\n")
        self.assertIn("<table class=\"md\"><tr><th>a</th><th>b</th></tr><tr><td><code>x</code></td>", rendered)
        self.assertIn("&lt;b&gt;y&lt;/b&gt;", rendered)
        self.assertIn("<li><b>two</b></li>", rendered)

    def test_nested_lists_follow_indentation_and_split_by_type(self):
        rendered = evidence.markdown_html("- a\n  - a1\n  - a2\n- b\n1. x\n   - x1\n2. y")
        self.assertEqual(rendered, "<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>"
                                   "<ol><li>x<ul><li>x1</li></ul></li><li>y</li></ol>")


if __name__ == "__main__":
    unittest.main()
