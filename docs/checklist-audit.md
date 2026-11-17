# Developer skills checklist audit

Review date: 2026-11-17. Baseline: `8d15642e450dc9f5824523db922ced3bac8c2832`, initially clean working tree.

The supplied checklist combines reproduced defects, policy preferences and proposals for new products/tooling. It is not a list of twenty proven bugs. The changes below preserve cloud/remote-DB approvals, evidence honesty, scope controls and the user's commit identity/attribution policy.

| Item | Assessment and delivered change | Limits / remaining work |
| --- | --- | --- |
| P0-01 routing | Confirmed excessive keyword routing. ROUTE-001 selects skills for actual effects and loads once per session. | Real DB/auth/payment effects still require owning safety skills. |
| P0-02 modes | Added Lightweight/Standard/Strict guidance and mode suggestions in `risk` output. | Human assessment can raise mode; mode is not a runtime authorization grant. |
| P0-03 isolation | Python guard was already labeled partial; macOS OS network wrapper already existed. Added fail-closed behavior for integration/performance/provider profiles without a suitable OS wrapper. | Linux/Windows have no bundled OS backend; risky profiles block there. No filesystem sandbox. Unit-only Python protection remains partial and suitable only for trusted pure tests. Provider host allowlists also block because the current OS wrapper cannot enforce them. |
| P0-04 FK | Confirmed blanket policy. Default now allows FK; explicit discouraged/forbidden remains supported. Skills follow project conventions. | No existing application constraints are changed. |
| P0-05 dependencies | Confirmed automatic UI CLI install. Now opt-in, numeric exact release required, explicit npm registry, no automatic force, backup on explicit replacement. | Caller reviews release/provenance; transitive dependencies are not locked. CodeGraph stays separately opt-in at latest, unchanged. |
| P0-06 gate | Confirmed automatic global hooks. Now opt-in, with project target support and existing debugging bypass. | Existing global installations are preserved until explicitly uninstalled; no user settings modified by this task. |
| P0-07 IDs | Confirmed duplicate EV31/32/33. Renumbered duplicate occurrences; validator and regression detect collisions. | Definition validation does not prove agent behavior. |
| P1-01 context | Removed repeated activation boilerplate; moved strict workflow out of router into an on-demand reference. | No token/latency performance claim without paired agent measurements. |
| P1-02 activation | Router separates conceptual Q&A from repository work; descriptions lose blanket question-trigger tail. | Optional gate remains stricter and heuristic. |
| P1-03 architecture | Router no longer mandates layers/folders. Backend already treated its layout as fallback; clarified its opener and duplication advice. | Existing framework patterns still take precedence. |
| P1-04 verification | Lightweight mode explicitly waives run/roster/trace/generated reports. Strict evidence tooling unchanged. | No loosening of report's explicit-run integrity checks. |
| P1-05 profiles | FK, comment style, test limits and protected paths already exist with type/choice validation; corrected defaults and added regression for explicit overrides. | Routing overrides and configurable verification-level schema are new features, not implemented. Workflow modes are guidance plus risk suggestions. |
| P1-06 behavioral runner | Valid new-feature proposal, not an existing defect. Added scenario-definition validator only. | Agent execution, semantic grading and success/false-block/token/time measurements are not implemented or claimed. They require an adapter and an independent grading/evidence contract. |
| P1-07 CI | Added offline unittest + scenario-validation matrix for Linux/macOS/Windows and Python 3.11/3.14; existing installer rollback tests are included. | Workflow not executed on hosted runners here. Browser/optional-capability tests can skip; no claim of all-platform success. |
| P1-08 multi-stack | Existing suite already contains framework/SQL/IaC parser fixtures. No evidence that parser coverage establishes runtime behavior. | Real React/Laravel/Django/ASP.NET and SQL Server/MySQL integration matrix remains unimplemented. Requires toolchain/engine fixtures and isolation. |
| P2-01 packaging | Added source-only ZIP builder with allowlist; excludes state/cache/dotfiles/logs and symlinks; regression covers exclusions. | Review and secret scan required before distribution; the provided ZIP was not available for inspection. |
| P2-02 comments | Confirmed forced block-comment default. Default style enforcement is off; explicit project style remains supported. | Language correctness checks remain. |
| P2-03 commits | Not adopted: conflicts with the user's explicit user-owned/no-AI-attribution policy. | A lower-priority team setting cannot override a user instruction. |
| P2-04 agents | Shared rules/runtime already support multiple hosts. Claude gate is now optional and supports project placement. | No claim of ChatGPT Skills marketplace packaging/certification. |
| P2-05 releases | Added changelog, source packager, regression and CI definitions. | Agent benchmarks, release publishing and version bump remain pending; working tree changes are not a published release. |

## Verification and recovery

Baseline focused suite: 90 tests passed (installer, risk/inventory, SQL/code checks, runner). This is baseline evidence for that scope, not complete preservation proof. Current full suite: `python3 -m unittest discover -s tests -t .` — 276 tests passed in 48.538s on this macOS machine. The final installer help-text edit additionally passed its focused help test. All 16 skills validate; scenario definitions validate; `scan-secrets --all` passed with zero findings; `check-code` reported 14 low-severity warnings; `git diff --check` passed. Source ZIP contained 168 allowlisted files with no excluded state/cache directories at inspection time. Logs are retained locally in `.devskills/checklist-audit/` (git-ignored). Tests use local temporary repositories, local processes, mock CLI binaries and synthetic records. No npm download, cloud/remote DB connection, global installation, commit or publication was performed.

Intentional changes: installer optional-tool/hook defaults, FK/comment defaults, scoped routing/workflow weight, duplicate scenario IDs and fail-closed risky test profiles. Existing explicit overrides, install backups/rollback, legacy guard cleanup and approval restrictions remain. The older full design plan is historical context; current `SKILL.md`, runtime, README and INSTALL describe these changes.

To inspect source without installing: `python3 agent-skills.py install --dry-run`. To package after review: `python3 tools/package-release.py /tmp/agent-skills.zip`, then inspect the ZIP and run the secret scanner. Revert the task diff to recover old source behavior; installed user settings were not touched. Do not use a downgrade to bypass the new isolation block for risky tests.
