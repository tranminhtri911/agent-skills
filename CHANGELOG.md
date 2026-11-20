# Changelog

Every committed change bumps the suite version by one patch step (1.0.0 → 1.0.1 → 1.0.2) in `pyproject.toml`, `src/devskills/__init__.py`, every `skills/*/SKILL.md` `metadata.version` and a section below; `SuiteVersionTest` fails when they disagree.

## 1.0.5 (2026-11-19)

- New `task-spec` skill (19th): one folder per task under the specs root turns a verbatim `require.md` into `plan.html` (overview with requirement mapping, current and target flow with diagrams, changes, impact, sub tasks, verify, tests, risks, questions to confirm, estimate, deploy — one block per page, small nested collapsible items, stat cards, step bar, light/dark), small `sub_tasks/taskNN_<slug>.md` files (overview, implementation, unit test, E2E test, verify) and a vi/en/ja `checklist.html` in the e2e-evidence schema (rules SPEC-001..009, scenario EV54). The folder keeps no JSON: pages embed their data.
- `ds.py spec init|build|source`: creates the task folder with a short `require.md`, validates the plan (flow diagrams required, readability limits on lines, cells and items), the sub task files and the checklist, sums total and remaining estimate, renders `plan.html` (inline SVG flow diagrams, offline) and `checklist.html`, and prints the embedded JSON back for the next edit. `.devskills.toml [spec] root` names the specs root.
- dev-orchestrate, design-change, e2e-evidence and the skill gate route plan/spec work to `task-spec`; e2e-evidence takes a spec's cases with `spec source --part checklist`.
- e2e-evidence: `checklist.html` uses the plan look (hero with live stats for ticked steps, OK, NG and untested; one card per case with preconditions and test data side by side; pill OK/NG toggles) and embeds its full data; summaries and plans render nested lists.
- e2e-evidence: `report.html` uses the same plan look — hero with the verdict and six stat cards, an overview card grouping every case NG → BLOCKED → PARTIAL → NOT RUN → OK (stacked rows on phones), one card per case with reason, conclusion, preconditions and test data, and one card per step with its result, expected and observed values and its own screenshot grid.

## 1.0.4 (2026-11-19)

- New `e2e-evidence` skill (18th): E2E and manual test runs by checklist leave the same evidence — a vi/en/ja `checklist.html` (left menu, collapsible cases with checkboxes, pages with totals) generated from the branch/prompt when missing, one folder per case with a screenshot per step, `summary_<case-id>.md` with an OK/NG/PARTIAL/BLOCKED/NOT_RUN result, one `report.html` per task — every case OK/NG with its reason and links first, then each case's checklist steps with the recorded result, observation and screenshots — under a gitignored evidence root (rules E2E-001..010, scenario EV53). Learned from a real manual run's evidence folder.
- `ds.py evidence init|checklist|report`: creates the task folder and the `.gitignore` entry, validates `checklist.json` and renders the checklist with its case folders, and builds the report from case summaries and screenshots (NG fails, missing evidence blocks; folders outside the checklist are listed, not counted). `.devskills.toml [evidence] root` names the evidence root.
- dev-orchestrate, test-safely and the skill gate route checklist/E2E evidence work to `e2e-evidence`.

## 1.0.3 (2026-11-19)

- Include responsive layout inspection in every UI E2E run.
- Reuse established UI patterns for development and maintenance. Consult the UI/UX skill for design gaps and during rendered review.

## 1.0.2 (2026-11-19)

- Route new UI design and rendered UI review to the available UI/UX skill, with responsive checks around affected breakpoints.
- Remove the GitHub Actions regression workflow.

## 1.0.1 (2026-11-17)

- Select skills by actual scope; add workflow modes and move Strict instructions to a reference.
- Make the UI reference install opt-in; add project gate support and require an explicit UI CLI release.
- Follow project FK/comment conventions with explicit overrides.
- Fail closed for risky test profiles without OS network isolation.
- Fix duplicate evaluation IDs; add definition validation, release-source packaging and CI matrix.
- Skill gate routes only the user's own words; pasted checklists, logs and documents no longer require every skill they mention.
- Comment templates no longer mandate block comments over the repository's style.
- Release ZIP excludes `*.egg-info/`; INSTALL documents building it with `tools/package-release.py`.
- New `code-style` skill (17th): explicit-over-short rules STYLE-001..007, per-language references (Python, TS/JS, Java, Kotlin, C#, PHP, Go, Swift, Dart, SQL) and per-framework references (Django, FastAPI, React/Next, Vue, Angular, NestJS, Spring, Android/Compose, ASP.NET Core, Laravel, SwiftUI, Flutter) with cited official sources; patterns applied by signal. Linked both ways with write-maintainable-code, routed by dev-orchestrate, review-code and the skill gate (scenario EV52).
- Automatic style routing: `ds.py style` (and a section in `inspect`) detects languages, frameworks and style tools per project root of a monorepo from manifests and file extensions (adds Flutter, Android/Compose, SwiftUI and the ASP.NET Core web SDK); the skill gate adds the matching code-style references as context, without blocking, on the first edit of each language in each root.
- OPS-014: classify command targets as proven local, non-local or unknown; tunnels, network mounts and indirect commands are not proof of local, and a timeout never approves a non-local target (scenarios EV50, EV51).
- The skill gate is installed by default by `install` and `update` (`--without-skill-gate` opts out; `--with-skill-gate` is kept and does nothing extra).
- Codex: `install --target codex` adds a non-blocking `apply_patch` hook to `~/.codex/hooks.json` that supplies the code-style references (`skill-gate.py codex-style`); it merges with existing hooks and needs one trust step in Codex `/hooks`.

See `docs/checklist-audit.md` for verification limits and proposed work not delivered.
