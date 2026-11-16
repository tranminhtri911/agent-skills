# Authorization and operations (OPS-001 … OPS-013)

Carry out the requested task and necessary supporting work. Authorization and preferences persist across turns. Local work does not need per-command confirmation; cloud access and every non-local database operation have the explicit approval requirements below.

## Local work

Read, copy, convert, transform, export and update local data directly when needed for the task. Run local builds/tests and clean artifacts created for the task. Local development DB changes, resets, rollbacks and disposable Docker volume cleanup can proceed when included in the user's request or necessary for an isolated test.

Determine the actual target from the command and available configuration without printing secrets. Preserve unrelated files, developer changes and data. Do not request a dangerous-command confirmation for local operations within the task, including data processing, DB resets, migrations and cleanup.

## Cloud access: warn and wait for approval (OPS-011)

Never independently connect to cloud or use any cloud profile, secret key, access key, token, service account, SSO session or ambient credentials. This applies to every cloud environment, including dev, STG/staging, production and sandboxes, through CLI, SDK, scripts, Terraform, MCP or another authenticated tool.

Before each cloud command/tool action, or an explicitly listed batch:

1. Show a warning with the exact command/actions, provider, account/profile, environment, target, expected effect and risks/costs. Redact secret values; never open credential files to prepare the warning.
2. Wait for the user's explicit approval covering those actions and targets. A general request to inspect, debug or test, existing credentials, an already logged-in session and a read-only label do not count as approval.
3. Execute only the approved actions. Do not repeat an approval already covering that exact list; new actions, changed accounts/profiles/targets or retries outside its scope need another warning and approval. No reply, elapsed time or a tool failure grants permission.

Read-only list/get/describe, identity checks such as `aws sts get-caller-identity`, login/token refresh, connection tests, inventories, remote state access and remote plans/dry runs all require approval. Do not make an identity or discovery call to fill in an unknown account before asking: report the unknown details and clarify the intended target first. A cloud DB reached through a localhost tunnel is still cloud access. Tests and scripts must be checked for hidden SDK calls and credential discovery, including metadata/SSO providers.

Genuinely offline source/document review and credential-free local mocks remain ordinary local work. A `--dry-run` flag does not establish that a command is offline. Existing stricter restrictions, including no-cloud or manual-only Azure operations, remain in force. This rule takes precedence over read-only exceptions elsewhere.

## Non-local databases: no operation without approval (OPS-012)

Never independently connect to or perform any operation on a database outside this machine, whether cloud or non-cloud, dev, STG/staging, production or another remote/shared environment. This covers all reads and writes: SELECT, schema/metadata inspection, estimated/actual EXPLAIN, health/connection checks, exports/dumps/backups, migrations, restores, permission changes and maintenance.

Before each action or explicitly listed batch, show a warning with the exact commands/queries, server/environment, database, purpose, expected effects and risks, then wait for explicit user approval covering those actions and targets. Existing credentials, a read-only account, an authenticated session and a general request to inspect/debug/test do not grant access. Do not repeat approval already covering the exact listed actions; additional queries, changed targets and retries outside the approved scope need a new warning and approval. Silence or elapsed time is not consent.

Judge the actual database target. CLI, ORM/SDK, apps/scripts/tests, MCP, SSH, localhost tunnels and remote Docker/Kubernetes contexts can all reach a non-local database. Do not connect or run a health/identity query to identify or validate an unknown target before approval. When there are concrete signs of a non-local database but its identity is unclear, stop and clarify the target before accessing it; do not assume a localhost port makes it local.

In-scope work on confirmed local databases and offline review of source or already-provided schema/dump files remain ordinary local work. Cloud databases also follow OPS-011, and approval does not waive test isolation or stricter user restrictions. OPS-012 overrides all read-only database exceptions, including estimated-plan guidance.

## Dangerous commands on other non-local servers

For operations outside cloud and database access, ask for confirmation when both conditions hold: the command has a destructive or operationally risky effect, and the affected target is known or reasonably suspected to be a non-local server, such as dev, STG/staging, production or shared development infrastructure. This includes data deletion/overwrites, permission changes, infrastructure mutations and deployment. Read-only inspection outside cloud and database access does not trigger this dangerous-command rule; cloud reads and non-local DB reads still require OPS-011/012 approval.

Judge the affected resource, not the machine launching the command. SSH sessions, remote Docker/Kubernetes contexts, cloud CLIs and localhost tunnels can affect remote servers. When concrete evidence suggests a remote target but it is unclear which server, clarify it before the dangerous step. Do not require proof or confirmation for every ordinary local command.

Before asking, check whether the conversation already authorizes the same environment, target and effect; do not ask again for covered steps. Otherwise state the exact target and effect, then wait for confirmation. Continue independent local work while waiting. Questions about missing requirements or unrelated scope expansions remain separate from this rule.

## When authorization matters

| Rules | Operations | Boundary |
| --- | --- | --- |
| OPS-001…003 | Branch/tag changes, history rewrites, discarding changes | In-scope local work proceeds without extra confirmation; dangerous changes to remote/shared refs need authorization for that effect. Preserve unrelated work. |
| OPS-004…005 | Database resets and bulk data changes | Process in-scope confirmed local data directly. Every non-local DB connection/operation requires OPS-012 approval. |
| OPS-006 | Nonlocal database operations | No connection or operation, including reads, without warning and explicit approval under OPS-012; cloud DB access also follows OPS-011. |
| OPS-007…008 | Docker volumes, recursive deletes, system changes | In-scope local work proceeds directly; dangerous changes on non-local servers need authorization. Preserve unrelated local resources. |
| OPS-009…010 | Cloud changes, deployment, publishing, messages, real payments | Follow explicit user restrictions and authorization. Prepare the concrete result before any approval request. |
| OPS-011 | Any cloud connection or use of cloud credentials | Warn and wait for explicit approval covering the exact actions and targets, including read-only, identity, login and connection checks. |
| OPS-012 | Every non-local database connection or operation | Warn and wait for explicit approval covering the exact actions and targets, including reads, schema/plans, health checks and backups, through direct or indirect access. |
| OPS-013 | Presentation of required approval requests | Use a supported interactive confirmation tool with a short icon/action/environment title and exact operation details; refusal first, explicit scoped approval second. Await the actual reply. |

Keep existing user restrictions on AWS/Azure, production, real payments, secret transmission and remote load tests. Tests continue to use isolated resources, environment allowlists and network restrictions. These test controls do not require an approval prompt for ordinary local work.

## Legacy guard removal

The automatic Bash guard hook and blanket permission `ask` rules are retired. Do not install them. `python3 agent-skills.py guard --remove` removes old devskills hooks/rules and preserves unrelated settings; `guard` without `--remove` performs the same cleanup. For project settings use `--target claude-project` and, for local settings, `--local`.

Apply the same authorization boundaries to shell commands and MCP tools. The retired guard does not enforce OPS-011/012 or produce a native approval dialog. Use the supported interactive question/confirmation UI under [OPS-013](approval-dialog.md), with an icon and short action title, and wait for explicit approval before cloud access or any non-local database operation. If no suitable UI tool exists, report the limitation and wait for consent in chat. Do not change session permissions to force a native dialog. No mandatory command table is required.
