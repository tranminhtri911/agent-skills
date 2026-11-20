"""`ds.py spec`: require.md, plan validation (diagrams, nesting, readability), sub tasks, pages with embedded data."""

from __future__ import annotations

import copy
import json
import unittest

from devskills import flow_diagram, spec
from tests._support import REPO_ROOT, commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write

PLAN = json.loads((REPO_ROOT / "skills/task-spec/assets/plan.example.json").read_text(encoding="utf-8"))
CHECKLIST = (REPO_ROOT / "skills/e2e-evidence/assets/checklist.example.json").read_text(encoding="utf-8")
SUBTASK = (REPO_ROOT / "skills/task-spec/assets/subtask.example.md").read_text(encoding="utf-8")


def block(plan, block_id):
    return next(item for item in plan["blocks"] if item["id"] == block_id)


class PlanValidationTest(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(spec.validate_plan(PLAN, "demo42"), [])

    def test_missing_block_bad_subtask_and_unknown_dependency(self):
        plan = copy.deepcopy(PLAN)
        plan["blocks"] = [item for item in plan["blocks"] if item["id"] != "deploy"]
        plan["subtasks"][0]["id"] = "T1"
        plan["subtasks"][1]["depends_on"] = ["task99"]
        plan["subtasks"][2]["estimate_hours"] = 0
        problems = "\n".join(spec.validate_plan(plan, "demo42"))
        for expected in ("`deploy` is missing", "subtasks[0].id", "subtasks[1].depends_on", "subtasks[2].estimate_hours"):
            self.assertIn(expected, problems)

    def test_flow_blocks_need_a_diagram_and_not_applicable_needs_a_reason(self):
        plan = copy.deepcopy(PLAN)
        del block(plan, "target_flow")["items"][0]["diagram"]
        deploy = block(plan, "deploy")
        deploy.clear()
        deploy.update({"id": "deploy", "not_applicable": "Không có bước riêng: release thường."})
        problems = "\n".join(spec.validate_plan(plan, "demo42"))
        self.assertIn("target_flow: a flow needs at least one diagram", problems)
        self.assertNotIn("deploy", problems)

    def test_nested_items_and_confirm_status(self):
        plan = copy.deepcopy(PLAN)
        block(plan, "changes")["items"][0]["items"][0]["items"] = [{"title": "x", "items": [{"title": "y", "body": "z"}]}]
        block(plan, "confirm")["items"][0]["status"] = "maybe"
        problems = "\n".join(spec.validate_plan(plan, "demo42"))
        self.assertIn("at most 3 levels", problems)
        self.assertIn("status: one of open, answered, n/a", problems)

    def test_bad_diagram_edge(self):
        plan = copy.deepcopy(PLAN)
        block(plan, "current_flow")["items"][0]["diagram"]["edges"].append({"from": "form", "to": "nowhere"})
        self.assertIn("from/to must be node ids", "\n".join(spec.validate_plan(plan, "demo42")))


class ReadabilityTest(unittest.TestCase):
    def test_long_line_and_cell_fail_long_item_warns(self):
        self.assertEqual(spec.readability_findings("- short\n- facts", "x"), [])
        long_line = spec.readability_findings("a" * 230, "x")
        self.assertEqual([(finding.rule_id, finding.severity) for finding in long_line], [("SPEC-LONG-LINE", "high")])
        cell = spec.readability_findings("| a | b |\n|---|---|\n| " + "c" * 150 + " | d |", "x")
        self.assertEqual(cell[0].rule_id, "SPEC-LONG-LINE")
        code = spec.readability_findings("```\n" + "x" * 300 + "\n```", "x")
        self.assertEqual(code, [], "code blocks keep exact long values")
        many = spec.readability_findings("\n".join(f"- line {number}" for number in range(25)), "x")
        self.assertEqual([(finding.rule_id, finding.severity) for finding in many], [("SPEC-ITEM-TOO-LONG", "medium")])


class FlowDiagramTest(unittest.TestCase):
    def test_layers_loop_and_unique_marker(self):
        diagram = {"nodes": [{"id": "a", "label": "Start", "kind": "start"},
                             {"id": "b", "label": "Check?", "kind": "decision"},
                             {"id": "c", "label": "Saved", "kind": "data", "state": "new"}],
                   "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"},
                             {"from": "b", "to": "a", "label": "retry"}]}
        self.assertEqual(flow_diagram.validate_diagram(diagram, "d"), [])
        svg = flow_diagram.render_diagram(diagram, "flow")
        self.assertIn('class="edge back"', svg, "an edge to an earlier node is drawn as a loop")
        self.assertIn("polygon", svg, "decisions are drawn as a hexagon")
        self.assertIn("s-new", svg)
        marker = svg.split('marker id="', 1)[1].split('"', 1)[0]
        self.assertIn(f"url(#{marker})", svg)
        self.assertIn("<li><b>Start</b>", svg, "the flow is also given as text")

    def test_wrap_counts_wide_characters(self):
        expected = ["案件登録案件登録", "案件登録案件登録", "案件登録"]
        self.assertEqual(flow_diagram.wrap_label("案件登録" * 5, 16), expected)


class SpecCommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_dir(self)
        init_git_repo(self.repo)
        write(self.repo, "README.md", "demo\n")
        commit_all(self.repo)
        self.task_dir = self.repo / "specs/demo42"
        self.scratch = make_temp_dir(self)
        self.plan_file = self.scratch / "plan.json"
        self.checklist_file = self.scratch / "checklist.json"
        self.plan_file.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
        self.checklist_file.write_text(CHECKLIST, encoding="utf-8")

    def prepare(self, with_all_subtasks: bool = True) -> None:
        self.assertEqual(run_cli("spec", "init", "--task", "demo42", cwd=self.repo).returncode, 0)
        with (self.task_dir / "require.md").open("a", encoding="utf-8") as require:
            require.write("\nKhách hàng: giá cả ngày phải hiện trong memo lịch.\n")
        for subtask in PLAN["subtasks"] if with_all_subtasks else PLAN["subtasks"][:2]:
            write(self.task_dir, f"sub_tasks/{spec.subtask_file_name(subtask)}", SUBTASK)

    def build(self, *extra: str):
        return run_cli_json("spec", "build", "--task", "demo42", *extra, cwd=self.repo)

    def test_init_writes_a_short_template_without_overwriting(self):
        code, payload = run_cli_json("spec", "init", "--task", "demo42", cwd=self.repo)
        self.assertEqual(code, 0)
        self.assertEqual(payload["gate_result"], "warn", "an empty require.md is reported")
        template = (self.task_dir / "require.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(template.splitlines()), 6)
        (self.task_dir / "require.md").write_text("my requirement\n", encoding="utf-8")
        run_cli("spec", "init", "--task", "demo42", cwd=self.repo)
        self.assertEqual((self.task_dir / "require.md").read_text(encoding="utf-8"), "my requirement\n")

    def test_build_writes_pages_without_json_files_and_rebuilds_from_embedded_data(self):
        self.prepare()
        code, payload = self.build("--plan", str(self.plan_file), "--checklist", str(self.checklist_file))
        self.assertEqual(code, 0, payload)
        self.assertEqual(sorted(path.name for path in self.task_dir.iterdir()),
                         ["checklist.html", "plan.html", "require.md", "sub_tasks"])
        page = (self.task_dir / "plan.html").read_text(encoding="utf-8")
        for marker in ('id="case-overview"', 'id="case-target_flow"', '<svg class="flow"', 'class="node k-decision s-new"',
                       'class="item depth-2"', 'href="sub_tasks/task01_memo-allday-lines.md"', 'class="stat"',
                       'class="pill st-open"', 'href="checklist.html"', 'id="plan-source"', 'data-step-page="12"'):
            self.assertIn(marker, page)
        self.assertLess(page.index('id="case-target_flow"'), page.index('id="case-subtasks"'))
        code, _ = self.build()
        self.assertEqual(code, 0, "a rebuild without --plan/--checklist uses the data embedded in the pages")
        source = run_cli("spec", "source", "--task", "demo42", "--part", "checklist", cwd=self.repo)
        self.assertEqual(json.loads(source.stdout)["cases"][0]["id"], "demo42-TC01")
        plan_out = self.scratch / "again.json"
        run_cli("spec", "source", "--task", "demo42", "--out", str(plan_out), cwd=self.repo)
        self.assertEqual(json.loads(plan_out.read_text(encoding="utf-8")), PLAN)

    def test_missing_subtask_section_requirement_and_long_line_fail(self):
        self.prepare(with_all_subtasks=False)
        write(self.task_dir, "sub_tasks/task02_form-pass-estimate.md", "# task02\n\n## Overview\n\n" + "x" * 230 + "\n")
        (self.task_dir / "require.md").write_text("# demo42\n\nNguồn:\n\n<!-- paste here -->\n", encoding="utf-8")
        code, payload = self.build("--plan", str(self.plan_file), "--checklist", str(self.checklist_file))
        self.assertEqual(code, 3)
        rules = {finding["rule_id"] for finding in payload["findings"]}
        self.assertTrue({"SPEC-SUBTASK-MISSING", "SPEC-SUBTASK-SECTION", "SPEC-REQUIRE-EMPTY", "SPEC-LONG-LINE"} <= rules)
        self.assertTrue((self.task_dir / "plan.html").is_file(), "the page is still written so the plan can be read")

    def test_stray_json_in_the_folder_is_reported(self):
        self.prepare()
        write(self.task_dir, "plan.json", "{}")
        _, payload = self.build("--plan", str(self.plan_file), "--checklist", str(self.checklist_file))
        self.assertIn("SPEC-STRAY-JSON", {finding["rule_id"] for finding in payload["findings"]})

    def test_invalid_plan_and_missing_plan_are_usage_errors(self):
        self.prepare()
        completed = run_cli("spec", "build", "--task", "demo42", cwd=self.repo)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("no plan", completed.stderr)
        plan = copy.deepcopy(PLAN)
        plan["schema"] = "other"
        self.plan_file.write_text(json.dumps(plan), encoding="utf-8")
        completed = run_cli("spec", "build", "--task", "demo42", "--plan", str(self.plan_file), cwd=self.repo)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("schema must be", completed.stderr)

    def test_existing_docs_specs_root_is_used(self):
        (self.repo / "docs/specs").mkdir(parents=True)
        run_cli("spec", "init", "--task", "t1", cwd=self.repo)
        self.assertTrue((self.repo / "docs/specs/t1/require.md").is_file())


if __name__ == "__main__":
    unittest.main()
