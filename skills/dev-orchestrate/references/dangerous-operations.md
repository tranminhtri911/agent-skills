# Authorization and operations (OPS-001 … OPS-010)

Carry out the requested task and necessary supporting work. Authorization and preferences persist across turns and cover the steps needed for that task; do not ask for another confirmation for every command.

## Local work

Read, copy, convert, transform, export and update local data directly when needed for the task. Run local builds/tests and clean artifacts created for the task. Local development DB changes, resets, rollbacks and disposable Docker volume cleanup can proceed when included in the user's request or necessary for an isolated test.

Determine the actual target from the command and available configuration without printing secrets. Preserve unrelated files, developer changes and data. Do not request a dangerous-command confirmation for local operations within the task, including data processing, DB resets, migrations and cleanup.

## Dangerous commands on non-local servers

Ask for confirmation only when both conditions hold: the command has a destructive or operationally risky effect, and the affected target is known or reasonably suspected to be a non-local server, such as dev, STG/staging, production or shared development infrastructure. This includes data deletion/overwrites, DB resets, permission changes, infrastructure mutations and deployment. Read-only remote inspection does not trigger this confirmation rule.

Judge the affected resource, not the machine launching the command. SSH sessions, remote Docker/Kubernetes contexts, cloud CLIs and localhost tunnels can affect remote servers. When concrete evidence suggests a remote target but it is unclear which server, clarify it before the dangerous step. Do not require proof or confirmation for every ordinary local command.

Before asking, check whether the conversation already authorizes the same environment, target and effect; do not ask again for covered steps. Otherwise state the exact target and effect, then wait for confirmation. Continue independent local work while waiting. Questions about missing requirements or unrelated scope expansions remain separate from this rule.

## When authorization matters

| Rules | Operations | Boundary |
| --- | --- | --- |
| OPS-001…003 | Branch/tag changes, history rewrites, discarding changes | In-scope local work proceeds without extra confirmation; dangerous changes to remote/shared refs need authorization for that effect. Preserve unrelated work. |
| OPS-004…005 | Database resets and bulk data changes | Process in-scope local data directly. Check the actual target; ask for dangerous changes only on known or suspected non-local servers without existing authorization. |
| OPS-006 | Nonlocal database operations | Ask only for destructive or operationally risky changes not already authorized for the environment and effect; read-only inspection does not trigger confirmation. |
| OPS-007…008 | Docker volumes, recursive deletes, system changes | In-scope local work proceeds directly; dangerous changes on non-local servers need authorization. Preserve unrelated local resources. |
| OPS-009…010 | Cloud changes, deployment, publishing, messages, real payments | Follow explicit user restrictions and authorization. Prepare the concrete result before any approval request. |

Keep existing user restrictions on AWS/Azure, production, real payments, secret transmission and remote load tests. Tests continue to use isolated resources, environment allowlists and network restrictions. These test controls do not require an approval prompt for ordinary local work.

## Legacy guard removal

The automatic Bash guard hook and blanket permission `ask` rules are retired. Do not install them. `python3 agent-skills.py guard --remove` removes old devskills hooks/rules and preserves unrelated settings; `guard` without `--remove` performs the same cleanup. For project settings use `--target claude-project` and, for local settings, `--local`.

Apply the same authorization boundaries to shell commands and MCP tools. No per-command approval protocol or mandatory command table is required.
