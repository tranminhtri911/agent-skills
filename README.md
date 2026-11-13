# devskills: software development skills for AI coding agents

A suite of 16 skills (Agent Skills / Claude Code) and a stdlib-only Python runtime (`ds.py`). The runtime turns important rules into evidence-based checks: understand code before editing, write maintainable code, protect databases/money/batches, test with isolated simulators, capture screenshots with baselines, review security, and **work within the user's authorization without repeated prompts for local tasks**.

Never fabricate data, code/APIs, sources, or results. Support important claims with inspected evidence, distinguish assumptions/mocks from reality, and label unverified work. Do requested work and necessary supporting changes; ask before extras. `trace` verifies tests only against exact passing testcases in reports; unexecuted, skipped, or unidentified tests remain `unverified`. Any unparseable file in a JUnit report set makes the runner `blocked`.

Maintenance, updates and refactors preserve behavior outside the requested change. Identify the actual old code/commit plus working-tree snapshot; list preserved cases and authorized differences. Specs support the comparison and cannot silently override legacy behavior. `trace` criteria tagged `preservation`/`refactor` require the same exact tests to pass in separate baseline/current runs with unchanged captured test sources and a current repository snapshot. See the [preservation contract](skills/write-maintainable-code/references/changing-existing-code.md#preservation-contract-for-maintenance-updates-and-refactors-chg-004005) and [baseline evidence schema](skills/write-maintainable-code/references/refactoring-workflow.md#5-prove-it). Fingerprints and test passes establish only the captured scope; review fixtures, configuration and old/new business flow explicitly.

Dangerous-command confirmation applies only to known or reasonably suspected non-local servers (dev, STG/staging, production or shared servers), unless the same target and effect are already authorized. In-scope local operations and read-only remote inspection do not need this confirmation.

- Installation, updates, removal: **[INSTALL.md](INSTALL.md)**
- Workflow diagrams: [docs/FLOW.md](docs/FLOW.md)
- Specification and rules (reviewed v1.1 plan): [docs/developer_skills_python_plan.md](docs/developer_skills_python_plan.md)

## Quick start

```bash
python3 -m unittest discover -s tests -t .   # verify (Python >= 3.11)
python3 agent-skills.py install              # install into ~/.claude/skills (no virtualenv required)
python3 agent-skills.py guard --remove       # existing installs: remove the legacy approval guard
```

## Python environment and optional virtualenv

**A virtualenv is not required.** `ds.py` uses only the standard library and runs on any installed Python ≥ 3.11. A virtualenv is for optional features and is created only when requested during installation.

| Need | Command |
| --- | --- |
| Core code/SQL/secret checks, safe tests, simulator, knowledge index without PDFs | `python3 agent-skills.py install` |
| Screenshots, fast image comparisons, PDFs, isolation from global/project Python environments | `python3 agent-skills.py install --with-venv` |
| Selected optional features | `python3 agent-skills.py install --with-venv --extras ui` (`ui`, `imaging`, `pdf`) |
| Latest CodeGraph | `python3 agent-skills.py install --with-codegraph` |
| Skip the default [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) UI reference | `python3 agent-skills.py install --without-ui-ux-pro-max` |
| Remove the virtualenv too | `python3 agent-skills.py uninstall --remove-venv` |

With `--with-venv`:

- The installer creates `~/.devskills/venv` **only if absent**, otherwise reuses it.
- Packages use the tested versions in [requirements-lock.txt](requirements-lock.txt): Playwright 1.64.1, Pillow 13.0.0, pypdf 6.21.3, plus Chromium.
- Each skill records this interpreter so `ds.py` uses it even inside projects with their own virtualenvs.
- Later updates preserve this choice.
- Routine skill use never creates virtualenvs automatically.

## Optional CodeGraph integration

[CodeGraph](https://github.com/colbymchenry/codegraph) builds a local call graph using tree-sitter and SQLite under `.codegraph/`, updating as files change. With the CLI installed and the project initialized, `ds.py inspect` adds:

- Index status.
- `codegraph-explore.md` with symbols, call paths, feature impact.
- Tests affected by current edits.

Skills also direct agents to read-only `codegraph explore/callers/impact/affected` instead of repeated search/read loops.

| `--codegraph` | Meaning |
| --- | --- |
| `auto` (default) | Use available CLI/index; otherwise skip |
| `on` | Require it; missing support gives `inspect` a warning gate |
| `off` | Never invoke it, e.g. when customer projects prohibit extra tools |

Precedence:

1. `ds.py inspect --codegraph off`
2. `DEVSKILLS_CODEGRAPH=off`
3. `.devskills.toml`: `[integrations] codegraph = "off"`
4. Default `auto`

The suite **never runs `codegraph init`/`index` automatically**: creating the index/file watcher is your choice. CodeGraph is not bundled. Add `--with-codegraph` to install/update to obtain the latest release (`npm install -g @colbymchenry/codegraph@latest`, without sudo). CodeGraph's README describes anonymous usage telemetry without code/filenames; use `codegraph telemetry off` when project agreements require it.

## Default UI reference: ui-ux-pro-max

[ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) is installed **by default** through its official CLI using the latest release:

```bash
python3 agent-skills.py install                          # install skills + ui-ux-pro-max
python3 agent-skills.py update                           # update ui-ux-pro-max to latest
python3 agent-skills.py install --without-ui-ux-pro-max  # skip it
```

- Missing `npx`/offline: warn and use built-in checklists. Explicit `--with-ui-ux-pro-max` makes installation failure fatal.
- The installer runs `npx -y ui-ux-pro-max-cli@latest init --ai <...> --force`, adding `--global` for user targets.
- `claude-user` installs under `~/.claude/skills/ui-ux-pro-max`; `claude-project` uses project `.claude/skills/`; `agents` uses `--ai universal`; `codex` uses `--ai codex`.
- Existing copies are backed up for rollback. Uninstall leaves this skill installed.

`implement-frontend` consults it **for every new screen/page/component or layout change**: layout, style, palette, typography, themes, UX, accessibility. Project design systems/tokens/components take precedence (CTX-009); it never restyles existing screens unasked. Default components use [shadcn/ui](https://ui.shadcn.com/), retaining an existing project kit instead. Follow requested devices; defaults are mobile + laptop for web and iOS + Android for mobile apps (tablet when requested). Light / Dark / System themes apply to existing themed projects, new apps, or requested dark mode. `verify-ui` reviews new/changed screens using its UX/accessibility guidance and captures light/dark where supported. `status` and `ds.py doctor` report availability.

**For repository developers** (test/lint with locked versions):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[ui,imaging,pdf,dev]" -c requirements-lock.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -t .
```

## Skills

| Skill | Use when |
| --- | --- |
| `dev-orchestrate` | Code changes: R0–R3, gates, rosters, final reports, authorization boundaries; preparing commits under the user's identity without AI attribution |
| `discover-codebase` | Understand entrypoints, callers, classes/functions/variables, DB tables, effects, tests |
| `design-change` | Senior recommendations: options, tradeoffs, risks, recovery; plans/specs in `docs/` |
| `write-maintainable-code` | Naming, language-correct comments/docstrings (`/* */` or `#`), structure, errors |
| `implement-backend` | Router → service → repository feature modules, jobs/batches, uploads, external clients |
| `design-api` | Contracts, required endpoint samples/`curl` (API-011), errors, pagination, versions, idempotency, webhooks |
| `implement-frontend` | Feature screens/components, UI states, accessibility, cleanup |
| `change-database` | Tables, indexes, query plans for large data (safe EXPLAIN per engine), transactions/rollback, locks, migrations, pools; limited FKs with integrity |
| `review-performance` | Threads/pools/async, leaks, CPU, N+1, before/after measurements |
| `design-reliability` | Retries, timeouts, fallbacks, outboxes, compensation, unknown outcomes |
| `review-security` | XSS, SQLi, traversal, SSRF, CSRF, IDOR, JWT, CORS, DoS/rates, secrets |
| `review-code` | Reviewing a diff/PR/MR or your own change: impact-ordered review routed to the domain skills, labeled findings (Conventional Comments), verdict |
| `design-infrastructure` | AWS/GCP VPCs, subnets, private networking, EC2/GCE, RDS/Cloud SQL, least-privilege IAM; Terraform/CloudFormation; agents never apply |
| `test-safely` | Money/batch/email/paid-API tests through mocks/simulators, isolated DBs |
| `verify-ui` | Fixed-profile screenshots, baseline comparisons, human baseline approval |
| `index-project-knowledge` | Create/check `.knowledge/INDEX.md` for md/docx/xlsx/pptx/pdf/html/csv |

## `ds.py` runtime

`doctor` · `run start/show` · `roster init/add/waive/show` · `attest` · `inspect` · `risk` · `check-code` · `check-sql` · `check-infra` · `scan-secrets` · `pool-budget` · `preflight` · `run-tests` · `native-checks` · `trace` · `api-diff` · `api-examples` · `footprint` · `simulate payment` · `screenshot` · `visual-diff` · `accept-baseline` · `rate-limit-probe` · `knowledge init/build/check` · `report` · `guard` · `validate-skills` · `help`. Use `ds.py help` for an overview/workflow, `ds.py help <command>` or `<command> --help` for explained arguments. The installer also provides `python3 agent-skills.py help [command]` with examples. `--json` is machine-readable; `--run <id>` records evidence.

API-011 automation: `DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>` (`api.examples`, required for API/API-spec changes). The optional `contracts` extra supplies schema validation. It checks sample coverage, schemas, curl and claimed local evidence across all operations in the supplied OpenAPI document, without executing requests. `run-tests --capture <path>` fingerprints fresh test-produced exchanges for local evidence. Review omitted routes and policy/business meaning separately. [Manifest, static fixture and support limits](skills/design-api/references/automatic-examples.md).

Primary evidence comes from native stack tools. `native-checks` reads package.json scripts, pyproject/manage.py, composer, go.mod, Cargo, csproj, Makefiles to run lint, type checking, builds, `manage.py check`, `makemigrations --check` safely. It never downloads tools or runs deploy/publish scripts; missing dependencies are blocked. `check-code` is supporting evidence. `trace` maps criteria to tests/checks/artifacts (verified/weak/failed/unverified); `api-diff` detects breaking OpenAPI changes. `inspect` lists **existing project conventions**: bases/mixins, shared modules, hooks, decorators, same-kind references, enums/constants, so new code reuses them. `GEN-HARDCODED-DOMAIN-VALUE` flags literals such as `'pending'`/`'sbf'` matching existing domain enums/constants (CODE-011). `inspect` also identifies **source patterns** (Repository, Service, Action, FormRequest, `selectors.py`…) and architecture libraries; skills follow them, adding patterns/layers/libraries only for named unsolved problems (DES-007/008). `footprint` measures new/existing code edits, protected paths, old migration edits, and scope; skills separate complex calculations from running logic (CHG-001..006).

Exit codes: `0` pass (possibly warnings), `2` invalid arguments/configuration, `3` failed checks, `4` blocked/missing capability, `5` internal errors.

## Developing the suite

```text
src/devskills/        stdlib runtime
skills/<skill>/      SKILL.md, references/, assets/, scripts/ds.py
tools/ds_shim.py      canonical shim -> python3 agent-skills.py sync
requirements-lock.txt exact tested optional-package versions
tests/               runtime/installer/package unittests, including real Chromium captures
evals/scenarios.json agent behavior scenarios
docs/                plan, workflow
```

- Refresh optional packages: update minimums in `pyproject.toml`, reinstall in `.venv`, run the full suite, then write `.venv/bin/python -m pip freeze --exclude-editable` to `requirements-lock.txt`, preserving the first two comment lines.
- Edit skills under `skills/<skill>/`, run `PYTHONPATH=src python3 -m devskills validate-skills skills`, then installer `status`/`update`.
- Edit `tools/ds_shim.py`, then run `python3 agent-skills.py sync`.
- Development installs can use `--link` so source changes apply immediately.
