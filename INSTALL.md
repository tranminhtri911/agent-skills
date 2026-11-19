# Installing devskills

## 1. Pre-install checks

```bash
# Python >= 3.11
python3 --version
# Run repository tests
python3 -m unittest discover -s tests -t .
# Preview installation without writing files
python3 agent-skills.py install --dry-run
# List commands and flags
python3 agent-skills.py help
python3 agent-skills.py help install
```

## 2. Installation

```bash
# Install 18 skills, the routing rule and the skill gate; no third-party UI tool by default
python3 agent-skills.py install
# Opt into an exact reviewed UI CLI release (replace X.Y.Z)
python3 agent-skills.py install --with-ui-ux-pro-max --ui-ux-version X.Y.Z
# Include the latest CodeGraph
python3 agent-skills.py install --with-codegraph
# Install selected skills
python3 agent-skills.py install --skills dev-orchestrate,discover-codebase,test-safely
# Project installation (commit .claude/skills for the team)
python3 agent-skills.py install --target claude-project --project /path/to/project
# Codex / Gemini CLI / Copilot CLI
python3 agent-skills.py install --target agents
python3 agent-skills.py install --target codex
# Development: symlink to this repository
python3 agent-skills.py install --link
# If ~/.claude/skills was just created, run this in Claude Code
/reload-skills
```

### Make agents actually use the skills

Skills load only when the agent decides a description matches. Tasks that arrive as pasted tickets, feasibility questions, specs or reviews often never trigger `dev-orchestrate`, and then no domain skill is routed. So `install` and `update` also write a short always-loaded rule ([tools/agent-rules.md](tools/agent-rules.md)) between `devskills:agent-rules` markers; later updates replace only that block, `uninstall` removes it, and the previous file is backed up under `~/.devskills/backups/agent-rules/`.

| Target | Rule written to | Read by |
| --- | --- | --- |
| `claude-user` (default) | `~/.claude/CLAUDE.md` | Claude Code, every project |
| `claude-project` | `<project>/CLAUDE.md` | Claude Code in that project |
| `codex` | `~/.codex/AGENTS.md` | Codex, every project |
| `agents`, `--target-dir` | nothing — use `rules` below | — |

```bash
# Skip it
python3 agent-skills.py install --without-agent-rules
# Add it to a chosen project: CLAUDE.md (Claude Code) and AGENTS.md (Codex, Copilot, Cursor…)
python3 agent-skills.py rules --project ~/work/shop
python3 agent-skills.py rules --project ~/work/shop --file agents   # or --file claude
python3 agent-skills.py rules --project ~/work/shop --remove
```

## 3. Optional features (screenshots, image comparison, PDF)

```bash
# Dedicated virtualenv (~/.devskills/venv): Playwright + Chromium, Pillow, pypdf
python3 agent-skills.py install --with-venv
# Playwright only
python3 agent-skills.py install --with-venv --extras ui
# Without a virtualenv: install into the installer's Python environment
python3 -m pip install "playwright==1.64.1" && python3 -m playwright install chromium
python3 -m pip install "pillow==13.0.0" "pypdf==6.21.3"
```

## Skill gate (force skills to be loaded at the right time)

Claude only loads skills when it chooses to. The skill gate makes that mandatory with Claude Code hooks:
a PreToolUse hook denies Edit/Write of code until the routed skills (from the file kind/path) were loaded with the Skill tool; UserPromptSubmit, SubagentStart and post-compaction hooks re-inject the rule; a Stop hook blocks a final report whose "Skills applied" lists skills never loaded.

It is installed by default with `install` and `update` for the Claude targets and for `--target codex` (the old `--with-skill-gate` flag is still accepted and does nothing extra). Opt out with `--without-skill-gate`:

```bash
python3 agent-skills.py install                                   # skills + rule + gate in ~/.claude
python3 agent-skills.py install --target claude-project           # gate in this project's .claude/settings.json
python3 agent-skills.py install --without-skill-gate              # skills and rule only
python3 tools/skill-gate/install.py --project /path/to/project --dry-run
python3 tools/skill-gate/install.py --project /path/to/project --uninstall
```

Uninstall removes the selected target's gate. Hook execution/state is independent of the host's dangerous-command approval policy.

**Codex.** `install --target codex` adds one hook to `~/.codex/hooks.json` (your existing hooks are kept, a backup is written) and copies the script to `~/.codex/hooks/`. It runs before `apply_patch` and adds the matching `code-style` references as context; it never blocks, because Codex has no Skill tool to prove a skill was loaded. Codex runs a new hook only after you trust it: open `/hooks` in Codex once.

Existing hooks in `~/.claude/settings.json` are kept; the first install writes a `settings.json.skill-gate-backup-*` copy.

Then open `/hooks` once or restart Claude Code. Debug escape hatch: `SKILL_GATE=off` or `touch ~/.claude/state/skill-gate/disabled`. Re-run the installer after editing `tools/skill-gate/skill-gate.py`.

## 4. Remove the legacy guard

The automatic approval guard is retired. **Cloud access still requires an agent warning and explicit user approval (OPS-011)** before any connection or use of a profile, secret/access key, token, service account, SSO session or ambient credentials, including read-only, identity/login/connection checks and remote plans/dry runs on every environment. The agent must show exact actions, account/profile, environment, target and risks/costs, then wait for approval covering those actions. This covers CLI, SDK, scripts, Terraform and MCP; available credentials or a general request to inspect/test never grant access. The always-loaded rule and skills carry this requirement; the retired guard does not enforce it or create a native approval dialog.

**Every non-local database connection or operation requires a warning and explicit approval (OPS-012)**, including SELECT, schema/plan inspection, health checks, backups, writes, migrations and maintenance, on cloud or non-cloud dev/STG/production or other remote/shared servers. Show exact commands/queries, server/environment, database, purpose and risks, and wait for approval covering those actions and targets. Existing credentials/sessions, localhost tunnels and general inspect/test requests do not grant access; do not connect to identify an unknown target before approval. This is also carried by the always-loaded rule and skills, without a native approval dialog.

Local data processing, confirmed local DB work, builds, tests and cleanup within the requested task do not require per-command confirmation. For remote operations outside cloud and database access, dangerous commands need approval for the same target and effect; read-only inspection does not trigger that dangerous-command rule. Existing stricter user restrictions still apply. See [authorization rules](skills/dev-orchestrate/references/dangerous-operations.md).

The installed always-loaded rule also requires **interactive confirmation (OPS-013)** when the host exposes a suitable tool: short icon/action/environment title, exact commands/queries and targets, purpose/risks, refusal first and scoped approval second. On the current Codex surface this uses `request_user_input_async`; an asynchronous tool return or preselected choice is not approval. Native command dialogs remain controlled by session policy (`approval_policy=never` does not produce a native command approval request). The installer does not change that policy or add an interception hook. If the interactive tool is unavailable, the agent reports that limitation and waits for consent in chat. See [approval-dialog.md](skills/dev-orchestrate/references/approval-dialog.md).

```bash
# Preview cleanup without changing settings
python3 agent-skills.py guard --remove --dry-run
# Remove devskills hooks and blanket ask rules from user settings (backed up first)
python3 agent-skills.py guard --remove
# Clean project settings, if the guard was installed there
python3 agent-skills.py guard --remove --target claude-project --project /path/to/project
python3 agent-skills.py guard --remove --target claude-project --project /path/to/project --local
```

Unrelated hooks, permissions and settings are preserved. `guard` without `--remove` also performs cleanup; it never enables a hook. New installations do not need this step.

## 5. Post-install checks

```bash
# Installed skills, local edits, backups, virtualenv, CodeGraph, ui-ux-pro-max
python3 agent-skills.py status
# Verification capabilities available on this machine
python3 ~/.claude/skills/dev-orchestrate/scripts/ds.py doctor
```

## 6. Optional project configuration (`.devskills.toml`)

```toml
[code]
# Multiline comments: block (/* */) | line | off
multiline_comment_style = "off"
# Flag literals matching existing domain enums/constants
hardcoded_values = true
# Minimum severity that fails a gate
fail_on = "high"

[database]
# auto | postgresql | mysql | sqlite | sqlserver | oracle | generic
engine = "postgresql"
# discouraged | forbidden | allowed
foreign_key_policy = "allowed"

[change]
# Protected paths require approval (footprint fails otherwise)
protected_paths = ["app/Services/Booking/BookingAmountCalculator.php", "billing/**"]

[integrations]
# auto | on | off
codegraph = "auto"
```

## 7. Daily workflow

```bash
# DS = python3 ~/.claude/skills/dev-orchestrate/scripts/ds.py
# Typical workflow and command explanations
DS help
DS help check-infra
# Start an evidence run
DS run start --label "add order cancel"
# Context map and project conventions (bases, enums, patterns)
DS inspect --feature order cancel --run <id>
# Risk and required-check roster
DS risk --run <id>
DS roster init --run <id> --risk R2
# Project-native lint/typecheck/build/Terraform checks (primary evidence)
DS native-checks --execute --run <id>
# Safe tests
DS preflight --run <id>
DS run-tests --run <id> --junit r.xml -- python -m pytest -q --junitxml=r.xml
# Supporting checks
DS check-code --run <id>
DS check-sql --run <id>
DS check-infra --run <id>
DS scan-secrets --run <id>
# Breaking API changes and existing-code impact
DS api-diff --spec docs/openapi.json --base-ref main --run <id>
DS api-examples --spec docs/openapi.json --file docs/api-examples.json --run <id>
DS footprint --base main --scope 'app/Services/Booking/**' --run <id>
# UI
DS screenshot --url http://127.0.0.1:3000/orders --viewport mobile --viewport desktop --run <id>
# Acceptance criteria linked to evidence, then final report
DS trace --run <id> --file acceptance.json
DS report --run <id> --summary-file summary.md
```

`trace` matches exact testcases (file/module, class, name, parameter ID), never aggregate pass counts. Rerun legacy records lacking testcase identities. Unexecuted/skipped tests remain `unverified`. Any unparseable JUnit file blocks the runner.

For maintenance/update/refactor, capture passing characterization tests in a separate baseline run **before editing**, then run the same tests in the implementation run. Tag unchanged-behavior criteria `preservation`/`refactor` and link `preservation.baseline_run`, `baseline_check`, and `baseline_state` (copy `details.source_state` from the baseline test record). `trace` rejects current-only proof, missing/mismatched snapshots, changed baseline test sources, stale current checks and skipped/unexecuted cases. An intentionally failing bugfix test uses a separate `regression` criterion. Schema, workflow and scope limits: [refactoring-workflow.md](skills/write-maintainable-code/references/refactoring-workflow.md#5-prove-it).

## 8. Updates / rollback

API-011 automation needs the optional `contracts` extra: `python3 -m pip install -e '.[contracts]' -c requirements-lock.txt`, or select it with `agent-skills.py install --with-venv --extras contracts` (combine with other desired extras explicitly). The core/default extras remain unchanged. The API/API-spec roster requires `api.examples`; missing schema support blocks. [Manifest, static fixture and exact limits](skills/design-api/references/automatic-examples.md). For local evidence the API test writes a redacted exchange under the current run, then `DS run-tests --capture <path> --junit <report> --run <id> -- <test command>` hashes that fresh output. `api-examples` requires matching capture/hash, exact passing current-run test identity and fresh local source state. It never executes the sample commands; review actual export scope and semantics separately.

```bash
# Identify outdated versions and manually edited files
python3 agent-skills.py status
# Update skills with backups; optional tools are unchanged
python3 agent-skills.py update
# Also update CodeGraph to latest
python3 agent-skills.py update --with-codegraph
# Replace local edits, keeping backups
python3 agent-skills.py update --force
# Restore the latest or a selected backup
python3 agent-skills.py rollback
python3 agent-skills.py rollback --backup 20261028T101500123456Z
```

### Sharing a release ZIP

Do not zip the working folder by hand (Finder/Explorer adds `__MACOSX/` and includes `.git/`, `.devskills/`, caches and logs). Build from the source allowlist, then check it:

```bash
python3 tools/package-release.py /tmp/agent-skills.zip
unzip -l /tmp/agent-skills.zip   # review docs/ before sharing outside the team
```

## 9. Uninstall

```bash
# Remove the guard
python3 agent-skills.py guard --remove
# Remove skills with backups; keep ui-ux-pro-max
python3 agent-skills.py uninstall
# Remove one skill
python3 agent-skills.py uninstall --skills verify-ui
# Also remove the virtualenv
python3 agent-skills.py uninstall --remove-venv
```

## 10. Troubleshooting

```bash
# Skills do not activate
/reload-skills
DS validate-skills ~/.claude/skills
# Python is too old
export DEVSKILLS_PYTHON=/path/to/python3.14
# Screenshots are BLOCKED
python3 agent-skills.py update --with-venv --extras ui
# Preflight blocks an .env file the tests do not load
DS preflight --dotenv-not-loaded .env --reason "tests use .env.testing"
# Tests require an explicitly approved provider sandbox host
DS run-tests --profile provider_sandbox --allow-host sandbox.provider.example -- <test command>
# Update reports "edited by hand"
python3 agent-skills.py update --force
# Terraform validate is BLOCKED before init (downloads providers, does not access state)
terraform init -backend=false
```
