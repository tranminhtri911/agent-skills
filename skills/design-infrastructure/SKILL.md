---
name: design-infrastructure
description: "Use when creating or changing cloud infrastructure or its code — AWS or GCP networks (VPC, subnets, NAT, security groups, firewall rules), compute (EC2, ECS, GKE), databases (RDS, Aurora, Cloud SQL), buckets, or IAM roles and policies — in Terraform, CloudFormation, CDK or Pulumi. Triggers (vi): hạ tầng, AWS, GCP, VPC, subnet, EC2, RDS, IAM, phân quyền cloud, security group, Terraform. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.4"
  suite: devskills
---

# Design Infrastructure

Private by default, least privilege always, everything in code, and nothing applied by the agent. Infrastructure mistakes are outages, data leaks and bills; the safe path is a reviewed plan applied by the owner.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

**Learn the existing setup first (CTX-009).** Read the repo's IaC layout (modules, environments, naming, tags, state backend, provider versions) and reuse its modules for VPC, IAM and databases; copy the reference module of the same kind. Follow the project's tool (Terraform, CDK, CloudFormation); never add a second one.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- New or widened access, public exposure, secrets → **REQUIRED:** review-security.
- More than one reasonable topology, or production impact → **REQUIRED:** design-change.
- Database engine, pool size or schema settings → **REQUIRED:** change-database.

## Safety (always)

- Before any cloud connection or use of a profile, key, token, service account, SSO session or ambient credentials, follow dev-orchestrate OPS-011: show the exact actions, account/profile, environment, target and risks/costs, then wait for explicit approval. This includes read-only inventory, identity/login/connection checks, remote state and remote plans/dry runs through CLI, SDK, scripts, Terraform or MCP. Do not call cloud to discover the account before approval. Credential-free local mocks and genuinely offline checks can proceed; stricter no-cloud/manual-only restrictions still apply.
- The agent writes code and runs only offline checks: `fmt`, `validate`, static scanners, `DS check-infra`. It never runs `apply`, `destroy`, `import`, `state` commands, cloud CLI writes, or `plan` against a real account or state backend without the user's explicit yes in this conversation; production never (dangerous operations).
- No credentials in code, tfvars, state outputs or the transcript; never read `~/.aws/credentials`, service-account keys or `.env`.
- `terraform init -backend=false` downloads providers: the user runs it, or approves it.

## Rules

- INF-001 least privilege: one role/service account per workload, never shared; actions enumerated from what the code actually calls, resources scoped to ARNs/resource names, conditions where they narrow access; no `*` actions, no admin/owner/editor for workloads.
- INF-002 private network: workloads and data in private subnets; only load balancers (and NAT) are public; no public SSH/RDP/DB ports; access via SSM Session Manager / IAP; security groups reference security groups, not CIDRs.
- INF-003 nothing public by accident: buckets, resource policies and IAM members never grant `*`, `allUsers` or `allAuthenticatedUsers` without a reviewed reason.
- INF-004 data: databases private, encrypted at rest (KMS), TLS required, backups/PITR, deletion protection on shared environments, multi-AZ/HA for production.
- INF-005 no long-lived credentials: instance profiles, task roles, IRSA/Pod Identity, OIDC federation for CI, Workload Identity; secrets in Secrets Manager / Secret Manager with rotation.
- INF-006 instances: IMDSv2 required, no public IP, encrypted volumes, patched images, managed access instead of SSH keys.
- Every resource tagged/labelled the project's way (owner, environment, cost centre); environments separated by account/project, not only by name.

Network, compute and database patterns for AWS and GCP: [network-and-data.md](references/network-and-data.md). Least-privilege IAM with examples and how to derive a policy from code: [iam-least-privilege.md](references/iam-least-privilege.md).

## Verify

1. `DS native-checks --execute --run <id>` → `terraform fmt -check`, `terraform validate` (once initialized), and checkov / trivy config / tflint when installed (primary evidence).
2. `DS check-infra --run <id>` → supporting signals: IAM wildcards, PassRole on `*`, public principals, unscoped GitHub OIDC trust, long-lived keys, primitive GCP roles, ports open to the internet, public or unencrypted databases, IMDSv1, public buckets.
3. The plan: the user runs `terraform plan` (or `cdk diff`, change set) and shares the output; review every `destroy`/`replace`, IAM and network change before anyone applies.
4. Report: what changed, blast radius, the IAM actions granted and why, rollback (previous version of the module), cost impact.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `Action: "s3:*"`, `Resource: "*"` "to make it work" | The calls the code makes (`s3:GetObject`, `s3:PutObject`) on `bucket/prefix/*` |
| One "app" role shared by API, worker and CI | A role per workload; CI assumes its own role via OIDC |
| RDS in a public subnet "for debugging" | Private subnet; connect through SSM port forwarding or a bastion-less tunnel |
| Security group `0.0.0.0/0` on 22 | Remove; SSM Session Manager / IAP TCP forwarding |
| Access keys in CI secrets | OIDC federation with a `sub` condition on repo and branch |
| `roles/editor` for a service account | Narrow predefined roles on the specific resource |
| Agent ran `terraform apply` to "test" | Never; the owner applies a reviewed plan |
