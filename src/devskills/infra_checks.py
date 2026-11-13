"""Static checks for infrastructure as code: least-privilege IAM and private-by-default networking (INF rules).

Supporting evidence next to the stack's own tools (terraform fmt/validate, checkov,
trivy, tflint, cfn-lint run by `native-checks`). Conservative text analysis of
Terraform (AWS/GCP providers), CloudFormation/SAM YAML or JSON and IAM policy JSON:
- IAM: `*` actions, service wildcards on sensitive services, write actions on `*`
  resources, NotAction allows, PassRole on `*`, public principals, unscoped GitHub
  OIDC trust, long-lived keys, GCP primitive roles and public members;
- network: SSH/RDP/database ports or all ports open to 0.0.0.0/0 or ::/0;
- data/compute: public databases, missing encryption, IMDSv1, public IPs, public buckets.
Findings are review signals; the agent confirms by reading the resource.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import PurePosixPath
from typing import Any

from devskills.fsutil import is_secret_file, read_text_limited, resolve_repo_root, select_target_files, utc_now_iso
from devskills.models import EXEC_COMPLETED, CheckResult, Finding, gate_from_findings
from devskills.output import emit_result, format_findings, severity_summary

ADMIN_PORTS = {22: "SSH", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 1433: "SQL Server", 1521: "Oracle",
               6379: "Redis", 11211: "Memcached", 27017: "MongoDB", 9200: "Elasticsearch", 5601: "Kibana",
               2375: "Docker API", 2379: "etcd", 9092: "Kafka"}
WEB_PORTS = {80, 443}
OPEN_CIDRS = ("0.0.0.0/0", "::/0")
SENSITIVE_SERVICES = {"iam", "sts", "kms", "organizations", "secretsmanager", "ssm", "lambda", "ec2", "s3"}
# Actions AWS only grants on Resource "*"; requiring an ARN there is impossible.
RESOURCELESS_ACTIONS = {"cloudwatch:putmetricdata", "xray:puttracesegments", "xray:puttelemetryrecords",
                        "ec2:createnetworkinterface", "ec2:deletenetworkinterface", "ec2:assignprivateipaddresses",
                        "ec2:unassignprivateipaddresses", "ecr:getauthorizationtoken", "sts:getcalleridentity",
                        "logs:createloggroup", "s3:listallmybuckets"}
READ_VERB = re.compile(r"^(get|list|describe|head|batchget|query|scan|view|lookup|search|select|check)", re.IGNORECASE)
PRIMITIVE_GCP_ROLES = {"roles/owner", "roles/editor"}
PUBLIC_GCP_MEMBERS = ("allUsers", "allAuthenticatedUsers")

_BLOCK_HEADER = re.compile(r'(?m)^\s*(resource|data)\s+"([\w-]+)"\s+"([\w-]+)"\s*\{')
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _finding(rule_id: str, severity: str, message: str, path: str, line: int, hint: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, path=path, line=line, hint=hint)


def _matching_brace(text: str, open_index: int) -> int:
    """Index of the `}`/`]` closing the bracket at open_index (quotes respected), or len(text)."""
    opening, closing = text[open_index], {"{": "}", "[": "]"}[text[open_index]]
    depth, in_string, index = 0, False, open_index
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text)


def _blocks(text: str) -> list[tuple[str, str, str, int]]:
    """Top-level Terraform `resource`/`data` blocks: (kind:type, name, body, line)."""
    found = []
    for match in _BLOCK_HEADER.finditer(text):
        end = _matching_brace(text, match.end() - 1)
        found.append((f"{match.group(1)}:{match.group(2)}", match.group(3), text[match.end():end],
                      text.count("\n", 0, match.start()) + 1))
    return found


def _nested(body: str, name: str) -> list[str]:
    """Bodies of nested blocks `name { ... }` (any depth)."""
    bodies = []
    for match in re.finditer(rf"(?m)^\s*{name}\s*\{{", body):
        bodies.append(body[match.end():_matching_brace(body, match.end() - 1)])
    return bodies


def _attribute(body: str, name: str) -> str | None:
    """Raw value of `name = value` on one line (the first occurrence)."""
    match = re.search(rf"(?m)^\s*{name}\s*=\s*(.+?)\s*$", body)
    return match.group(1) if match else None


def _strings(value: str | None) -> list[str]:
    return _STRING.findall(value or "")


def _list_attribute(body: str, name: str) -> list[str]:
    """Strings of `name = [ ... ]` possibly spanning lines, or of a single string value."""
    match = re.search(rf"(?m)^\s*{name}\s*=\s*", body)
    if not match:
        return []
    rest = body[match.end():]
    if rest.startswith("["):
        return _STRING.findall(rest[:_matching_brace(rest, 0) + 1])
    return _strings(rest.split("\n", 1)[0])


# --------------------------------------------------------------------------- IAM statements


def _evaluate_statement(statement: dict[str, Any], path: str, line: int) -> list[Finding]:
    """IAM rules for one Allow statement: {actions, not_actions, resources, principals, has_condition, text}."""
    findings: list[Finding] = []
    actions = [action.lower() for action in statement["actions"]]
    resources = statement["resources"]
    if statement["not_actions"]:
        findings.append(_finding("INF-IAM-NOT-ACTION", "high", "Allow with NotAction grants everything else", path, line,
                                 "list the actions the workload needs instead (INF-001)"))
    if "*" in actions or "*:*" in actions:
        findings.append(_finding("INF-IAM-ADMIN", "critical", "Allow on every action (*)", path, line,
                                 "grant the exact actions the code calls, on its own resources (INF-001)"))
    else:
        for action in actions:
            service, _, verb = action.partition(":")
            if verb == "*" and service in SENSITIVE_SERVICES:
                findings.append(_finding("INF-IAM-SERVICE-WILDCARD", "high", f"`{action}` grants every {service} action",
                                         path, line, "enumerate the actions; split read and write roles (INF-001)"))
            elif verb == "*":
                findings.append(_finding("INF-IAM-SERVICE-WILDCARD", "medium", f"`{action}` grants every {service} action",
                                         path, line, "enumerate the actions the workload calls (INF-001)"))
        if "*" in resources:
            if "iam:passrole" in actions:
                findings.append(_finding("INF-IAM-PASSROLE", "high", "iam:PassRole on every role (privilege escalation)",
                                         path, line, "restrict Resource to the role ARNs this service passes (INF-001)"))
            writes = [action for action in actions if action not in RESOURCELESS_ACTIONS
                      and not READ_VERB.match(action.partition(":")[2]) and action != "iam:passrole"]
            if writes:
                findings.append(_finding("INF-IAM-RESOURCE-WILDCARD", "medium" if statement["has_condition"] else "high",
                                         f"write actions on Resource \"*\": {', '.join(sorted(writes)[:4])}", path, line,
                                         "scope Resource to ARNs (bucket/prefix, table, secret, key) (INF-001)"))
    principals = statement["principals"]
    if ("*" in principals) and not statement["has_condition"]:
        findings.append(_finding("INF-IAM-PUBLIC-PRINCIPAL", "critical", "resource policy allows any principal (*)",
                                 path, line, "name the accounts/roles, or add conditions such as aws:SourceVpce (INF-003)"))
    text = statement["text"]
    if "token.actions.githubusercontent.com" in text and "token.actions.githubusercontent.com:sub" not in text:
        findings.append(_finding("INF-IAM-OIDC-UNSCOPED", "high", "GitHub OIDC trust without a `sub` condition", path, line,
                                 "pin repo:<org>/<repo>:ref:refs/heads/main (or environment) in a StringEquals/StringLike sub condition"))
    return findings


def _hcl_policy_statements(body: str) -> list[dict[str, Any]]:
    """`statement { ... }` blocks of an aws_iam_policy_document."""
    statements = []
    for statement in _nested(body, "statement"):
        if (_strings(_attribute(statement, "effect")) or ["Allow"])[0] != "Allow":
            continue
        principals = [identifier for block in _nested(statement, "principals") for identifier in _list_attribute(block, "identifiers")]
        statements.append({"actions": _list_attribute(statement, "actions"), "not_actions": _list_attribute(statement, "not_actions"),
                           "resources": _list_attribute(statement, "resources"), "principals": principals,
                           "has_condition": bool(_nested(statement, "condition")), "text": statement})
    return statements


_EFFECT_ALLOW = re.compile(r'"?Effect"?\s*[:=]\s*"?Allow"?')
_KEY_VALUE = r'(?<![A-Za-z])"?{key}"?\s*[:=]\s*(\[[^\]]*\]|"[^"]*"|\{{[^}}]*\}})'


def _object_around(text: str, index: int) -> str:
    """The innermost `{...}` object containing index (JSON, jsonencode or heredoc policies)."""
    depth = 0
    for start in range(index, -1, -1):
        if text[start] == "}":
            depth += 1
        elif text[start] == "{":
            if depth == 0:
                return text[start:_matching_brace(text, start) + 1]
            depth -= 1
    return text[index:index + 2000]


def _json_like_statements(text: str) -> list[tuple[dict[str, Any], int]]:
    """Allow statements written as JSON / HCL objects (`Effect = "Allow"`, `"Effect": "Allow"`)."""
    statements = []
    for match in _EFFECT_ALLOW.finditer(text):
        statement = _object_around(text, match.start())

        def values(key: str, statement: str = statement) -> list[str]:
            found = re.search(_KEY_VALUE.format(key=key), statement)
            if not found:
                return []
            raw = found.group(1)
            # Principal = { AWS = "*" } / "Principal": "*"
            return _STRING.findall(raw) if not raw.startswith('"') else [raw.strip('"')]

        principal_values = values("Principal")
        statements.append(({"actions": values("Action"), "not_actions": values("NotAction"), "resources": values("Resource"),
                            "principals": [value for value in principal_values if value == "*"],
                            "has_condition": bool(re.search(r'"?Condition"?\s*[:=]', statement)), "text": statement},
                           text.count("\n", 0, match.start()) + 1))
    return statements


def _yaml_items(text: str, anchor: re.Pattern[str]) -> list[tuple[str, int]]:
    """CloudFormation YAML list items (`- Key: ...` blocks) containing a line that matches anchor: (item text, line)."""
    lines = text.splitlines()
    items = []
    for index, line in enumerate(lines):
        if not anchor.search(line):
            continue
        key_column = len(line) - len(line.lstrip(" -"))
        start = index
        # The item starts at the closest `- ` line above whose dash sits left of the anchor's key.
        while start >= 0 and not (lines[start].lstrip(" ").startswith("- ")
                                  and len(lines[start]) - len(lines[start].lstrip(" ")) < key_column):
            start -= 1
        start = max(start, 0) if start >= 0 else index
        dash_column = len(lines[start]) - len(lines[start].lstrip(" "))
        end = index + 1
        while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip(" ")) > dash_column):
            end += 1
        items.append(("\n".join(lines[start:end]), start + 1))
    return items


def _yaml_values(item: str, key: str) -> list[str]:
    match = re.search(rf"(?m)^[ \-]*{key}:[ \t]*(.*)$", item)
    if not match:
        return []
    inline = match.group(1).strip()
    if inline:
        return [value.strip().strip("'\"") for value in inline.strip("[]").split(",") if value.strip()]
    following = item[match.end():].splitlines()[1:]
    values = []
    for line in following:
        if not line.lstrip().startswith("- "):
            break
        values.append(line.strip()[2:].strip().strip("'\""))
    return values


def _yaml_statements(text: str) -> list[tuple[dict[str, Any], int]]:
    statements = []
    for item, line in _yaml_items(text, re.compile(r"^[ \-]*Effect:\s*['\"]?Allow")):
        principals = _yaml_values(item, "AWS") + _yaml_values(item, "Principal")
        statements.append(({"actions": _yaml_values(item, "Action"), "not_actions": _yaml_values(item, "NotAction"),
                            "resources": _yaml_values(item, "Resource"), "principals": [value for value in principals if value == "*"],
                            "has_condition": "Condition:" in item, "text": item}, line))
    return statements


# --------------------------------------------------------------------------- network and resources


def _port_range(body: str, low: str, high: str) -> tuple[int, int] | None:
    """(from, to) or None for all ports (protocol -1/all or 0-65535)."""
    protocol = (_strings(_attribute(body, "protocol")) or _strings(_attribute(body, "ip_protocol")) or [""])[0]
    if protocol in ("-1", "all"):
        return None
    try:
        start = int((_attribute(body, low) or "0").strip('"'))
        end = int((_attribute(body, high) or str(start)).strip('"'))
    except ValueError:
        return None
    return (start, end) if not (start <= 0 and end >= 65535) else None


def _exposure(ports: tuple[int, int] | None, path: str, line: int, where: str) -> list[Finding]:
    if ports is None:
        return [_finding("INF-NET-PUBLIC-ALL", "high", f"{where}: all ports open to the internet", path, line,
                         "allow only the load balancer/security group that needs it (INF-002)")]
    exposed = [name for port, name in ADMIN_PORTS.items() if ports[0] <= port <= ports[1]]
    if exposed:
        return [_finding("INF-NET-PUBLIC-ADMIN", "high", f"{where}: {', '.join(exposed)} open to the internet", path, line,
                         "no public admin/DB ports: SSM Session Manager / IAP, private subnets, SG-to-SG rules (INF-002)")]
    if set(range(ports[0], ports[1] + 1)) <= WEB_PORTS:
        return []
    return [_finding("INF-NET-PUBLIC-INGRESS", "medium", f"{where}: ports {ports[0]}-{ports[1]} open to the internet", path, line,
                     "put the service behind a load balancer; open only 80/443 publicly (INF-002)")]


def _is_open(body: str) -> bool:
    values = _list_attribute(body, "cidr_blocks") + _list_attribute(body, "ipv6_cidr_blocks") \
        + _strings(_attribute(body, "cidr_ipv4")) + _strings(_attribute(body, "cidr_ipv6")) + _list_attribute(body, "source_ranges")
    return any(value in OPEN_CIDRS for value in values)


def _is_true(body: str, name: str) -> bool:
    return (_attribute(body, name) or "").strip().lower() == "true"


def _is_false(body: str, name: str) -> bool:
    return (_attribute(body, name) or "").strip().lower() == "false"


def _network_rules(resource_type: str, where: str, body: str, path: str, line: int) -> list[Finding]:
    """Ingress open to the internet: AWS security groups/rules, GCP firewall rules, public subnets."""
    findings: list[Finding] = []
    if resource_type == "aws_security_group":
        for ingress in _nested(body, "ingress"):
            if _is_open(ingress):
                findings += _exposure(_port_range(ingress, "from_port", "to_port"), path, line, where)
    elif resource_type in ("aws_security_group_rule", "aws_vpc_security_group_ingress_rule") and _is_open(body):
        if resource_type == "aws_vpc_security_group_ingress_rule" or "ingress" in (_attribute(body, "type") or ""):
            findings += _exposure(_port_range(body, "from_port", "to_port"), path, line, where)
    elif resource_type == "google_compute_firewall" and _is_open(body) and "EGRESS" not in (_attribute(body, "direction") or ""):
        for allow in _nested(body, "allow"):
            ports = _list_attribute(allow, "ports")
            if not ports:
                findings += _exposure(None, path, line, where)
            for port in ports:
                low, _, high = port.partition("-")
                if low.isdigit() and (high or low).isdigit():
                    findings += _exposure((int(low), int(high or low)), path, line, where)
    elif resource_type == "aws_subnet" and _is_true(body, "map_public_ip_on_launch"):
        findings.append(_finding("INF-NET-PUBLIC-SUBNET", "low", f"{where} assigns public IPs on launch", path, line,
                                 "only load balancer/NAT subnets are public; workloads live in private subnets (INF-002)"))
    return findings


def _aws_database_rules(where: str, body: str, path: str, line: int) -> list[Finding]:
    findings: list[Finding] = []
    if _is_true(body, "publicly_accessible"):
        findings.append(_finding("INF-DB-PUBLIC", "critical", f"{where} is publicly accessible", path, line,
                                 "private DB subnet group, publicly_accessible = false (INF-004)"))
    if not _is_true(body, "storage_encrypted") and "replicate_source_db" not in body:
        findings.append(_finding("INF-DB-UNENCRYPTED", "medium", f"{where} without storage_encrypted = true", path, line,
                                 "encrypt at rest (KMS); it cannot be turned on later without a copy (INF-004)"))
    if re.search(r'(?m)^\s*(master_)?password\s*=\s*"[^"$]+"', body):
        findings.append(_finding("INF-DB-PASSWORD-LITERAL", "high", f"{where} has a literal password", path, line,
                                 "manage_master_user_password = true (Secrets Manager) or a secret reference (INF-005)"))
    if (_attribute(body, "backup_retention_period") or "").strip() == "0":
        findings.append(_finding("INF-DB-NO-BACKUP", "medium", f"{where} keeps no backups", path, line,
                                 "backup_retention_period >= 7 and point-in-time recovery (INF-004)"))
    if not _is_true(body, "deletion_protection"):
        findings.append(_finding("INF-DB-NO-DELETION-PROTECTION", "low", f"{where} without deletion_protection", path, line,
                                 "deletion_protection = true for shared/prod databases (INF-004)"))
    return findings


def _gcp_database_rules(where: str, body: str, path: str, line: int) -> list[Finding]:
    findings: list[Finding] = []
    authorized = [value for network in _nested(body, "authorized_networks") for value in _strings(_attribute(network, "value"))]
    if any(value in OPEN_CIDRS for value in authorized):
        findings.append(_finding("INF-DB-PUBLIC", "critical", f"{where} authorizes 0.0.0.0/0", path, line,
                                 "private IP + Cloud SQL Auth Proxy / connectors (INF-004)"))
    if _is_true(body, "ipv4_enabled") and "private_network" not in body:
        findings.append(_finding("INF-DB-PUBLIC-IP", "medium", f"{where} has a public IP and no private network", path, line,
                                 "ipv4_enabled = false with private_network (INF-004)"))
    if "ALLOW_UNENCRYPTED_AND_ENCRYPTED" in body or _is_false(body, "require_ssl"):
        findings.append(_finding("INF-DB-NO-TLS", "medium", f"{where} accepts unencrypted connections", path, line,
                                 "ssl_mode = \"ENCRYPTED_ONLY\" (or TRUSTED_CLIENT_CERTIFICATE_REQUIRED) (INF-004)"))
    return findings


def _aws_compute_rules(where: str, body: str, path: str, line: int) -> list[Finding]:
    findings: list[Finding] = []
    metadata = _nested(body, "metadata_options")
    if not metadata or "required" not in (_attribute(metadata[0], "http_tokens") or ""):
        findings.append(_finding("INF-EC2-IMDSV1", "medium", f"{where} does not require IMDSv2", path, line,
                                 "metadata_options { http_tokens = \"required\" } (INF-006)"))
    if _is_true(body, "associate_public_ip_address"):
        findings.append(_finding("INF-EC2-PUBLIC-IP", "medium", f"{where} gets a public IP", path, line,
                                 "private subnet behind a load balancer; SSM for access (INF-002)"))
    if any(_is_false(device, "encrypted") for device in _nested(body, "root_block_device") + _nested(body, "ebs")):
        findings.append(_finding("INF-EC2-UNENCRYPTED", "medium", f"{where} has an unencrypted volume", path, line,
                                 "encrypted = true (or account-level EBS encryption by default) (INF-004)"))
    return findings


def _gcp_compute_rules(where: str, body: str, path: str, line: int) -> list[Finding]:
    findings: list[Finding] = []
    if any(_nested(interface, "access_config") for interface in _nested(body, "network_interface")):
        findings.append(_finding("INF-GCE-PUBLIC-IP", "medium", f"{where} has an external IP", path, line,
                                 "no access_config; Cloud NAT for egress, IAP for access (INF-002)"))
    if any("cloud-platform" in account and "email" not in account for account in _nested(body, "service_account")):
        findings.append(_finding("INF-GCE-DEFAULT-SA", "medium", f"{where} uses the default SA with cloud-platform scope", path,
                                 line, "a dedicated service account with only the roles it needs (INF-001)"))
    return findings


def _storage_and_identity_rules(resource_type: str, where: str, body: str, path: str, line: int) -> list[Finding]:
    """Public buckets, long-lived keys, user-attached policies, GCP bindings."""
    findings: list[Finding] = []
    if resource_type in ("aws_s3_bucket_acl", "aws_s3_bucket") and re.search(r'acl\s*=\s*"public-read', body):
        findings.append(_finding("INF-S3-PUBLIC", "critical", f"{where} is public via ACL", path, line,
                                 "private bucket + CloudFront OAC or presigned URLs (INF-003)"))
    elif resource_type == "aws_s3_bucket_public_access_block" and any(
            _is_false(body, flag) for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")):
        findings.append(_finding("INF-S3-PUBLIC", "high", f"{where} disables a public access block", path, line,
                                 "keep all four flags true unless a reviewed public website needs otherwise (INF-003)"))
    elif resource_type in ("aws_iam_access_key", "google_service_account_key"):
        findings.append(_finding("INF-IAM-LONG-LIVED-KEY", "high", f"{where} creates a long-lived key", path, line,
                                 "use roles: instance profile, task role, IRSA, OIDC federation, Workload Identity (INF-005)"))
    elif resource_type in ("aws_iam_user_policy", "aws_iam_user_policy_attachment"):
        findings.append(_finding("INF-IAM-USER-POLICY", "medium", f"{where} attaches permissions to an IAM user", path, line,
                                 "humans via SSO permission sets, workloads via roles (INF-005)"))
    elif re.match(r"google_\w+_iam_(member|binding|policy)$", resource_type):
        findings += _gcp_binding_rules(resource_type, where, body, path, line)
    return findings


def _gcp_binding_rules(resource_type: str, where: str, body: str, path: str, line: int) -> list[Finding]:
    findings: list[Finding] = []
    roles = _strings(_attribute(body, "role"))
    members = _strings(_attribute(body, "member")) + _list_attribute(body, "members")
    if any(role in PRIMITIVE_GCP_ROLES for role in roles):
        findings.append(_finding("INF-GCP-PRIMITIVE-ROLE", "high", f"{where} grants {roles[0]}", path, line,
                                 "a predefined narrow role on the specific resource, or a custom role (INF-001)"))
    if any(member in PUBLIC_GCP_MEMBERS for member in members):
        findings.append(_finding("INF-GCP-PUBLIC-MEMBER", "critical", f"{where} grants access to allUsers/allAuthenticatedUsers",
                                 path, line, "grant named service accounts or groups only (INF-003)"))
    impersonation = ("roles/iam.serviceAccountUser", "roles/iam.serviceAccountTokenCreator")
    if resource_type.startswith("google_project_iam") and any(role in impersonation for role in roles):
        findings.append(_finding("INF-GCP-PROJECT-IMPERSONATION", "medium", f"{where} allows impersonating every SA in the project",
                                 path, line, "grant it on the one service account (google_service_account_iam_member) (INF-001)"))
    return findings


def check_terraform(rel_path: str, text: str) -> list[Finding]:
    """Rules for Terraform resources of the AWS and Google providers, plus inline IAM policies anywhere in the file."""
    findings: list[Finding] = []
    for kind, name, body, line in _blocks(text):
        resource_type = kind.split(":", 1)[1]
        where = f"{resource_type}.{name}"
        findings += _network_rules(resource_type, where, body, rel_path, line)
        if resource_type in ("aws_db_instance", "aws_rds_cluster"):
            findings += _aws_database_rules(where, body, rel_path, line)
        elif resource_type == "google_sql_database_instance":
            findings += _gcp_database_rules(where, body, rel_path, line)
        elif resource_type in ("aws_instance", "aws_launch_template"):
            findings += _aws_compute_rules(where, body, rel_path, line)
        elif resource_type == "google_compute_instance":
            findings += _gcp_compute_rules(where, body, rel_path, line)
        elif resource_type == "aws_iam_policy_document" and kind.startswith("data:"):
            for statement in _hcl_policy_statements(body):
                findings += _evaluate_statement(statement, rel_path, line)
        else:
            findings += _storage_and_identity_rules(resource_type, where, body, rel_path, line)
    # Inline policies (jsonencode/heredoc): aws_iam_policy, role and bucket policies, trust policies.
    for statement, line in _json_like_statements(text):
        findings += _evaluate_statement(statement, rel_path, line)
    return findings


def check_cloudformation(rel_path: str, text: str) -> list[Finding]:
    """CloudFormation/SAM YAML or JSON: IAM statements, open security group ingress, public DB flags."""
    findings: list[Finding] = []
    is_json = rel_path.endswith(".json")
    statements = _json_like_statements(text) if is_json else _yaml_statements(text)
    for statement, line in statements:
        findings += _evaluate_statement(statement, rel_path, line)
    if not is_json:
        for item, line in _yaml_items(text, re.compile(r"CidrIp(v6)?:\s*['\"]?(0\.0\.0\.0/0|::/0)")):
            protocol = (_yaml_values(item, "IpProtocol") or [""])[0]
            try:
                ports = None if protocol in ("-1", "all") else (int(_yaml_values(item, "FromPort")[0]), int(_yaml_values(item, "ToPort")[0]))
            except (IndexError, ValueError):
                ports = None
            findings += _exposure(ports, rel_path, line, "SecurityGroupIngress")
    for match in re.finditer(r"PubliclyAccessible\"?\s*:\s*['\"]?true", text, re.IGNORECASE):
        findings.append(_finding("INF-DB-PUBLIC", "critical", "RDS PubliclyAccessible: true", rel_path,
                                 text.count("\n", 0, match.start()) + 1, "private DB subnet group (INF-004)"))
    return findings


def check_policy_json(rel_path: str, text: str) -> list[Finding]:
    """A standalone IAM policy document (JSON with Statement)."""
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return []
    findings: list[Finding] = []
    for statement, line in _json_like_statements(text):
        findings += _evaluate_statement(statement, rel_path, line)
    return findings


def check_infra_file(rel_path: str, text: str) -> list[Finding]:
    """Dispatch by file kind; files that are not infrastructure return nothing."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix == ".tf":
        return check_terraform(rel_path, text)
    if suffix in (".yaml", ".yml", ".json", ".template") and ("AWSTemplateFormatVersion" in text or "AWS::" in text):
        return check_cloudformation(rel_path, text)
    if suffix == ".json" and '"Statement"' in text and '"Effect"' in text:
        return check_policy_json(rel_path, text)
    return []


def run(args: argparse.Namespace) -> int:
    """CLI handler for `check-infra`."""
    repo_root = resolve_repo_root(args.repo)
    started_at = utc_now_iso()
    scope = "paths" if args.paths else ("all" if args.all else "changed")
    targets = [path for path in select_target_files(repo_root, args.paths, scope, args.base)
               if PurePosixPath(path).suffix.lower() in (".tf", ".yaml", ".yml", ".json", ".template") and not is_secret_file(path)]
    findings: list[Finding] = []
    checked = 0
    for rel_path in targets:
        text = read_text_limited(repo_root / rel_path)
        if text is None:
            continue
        file_findings = check_infra_file(rel_path, text)
        checked += bool(file_findings) or rel_path.endswith(".tf") or "AWS::" in text
        findings += file_findings
    fail_on = args.fail_on or "high"
    result = CheckResult(
        check_id=args.check_id, tool="devskills.check-infra", execution_status=EXEC_COMPLETED,
        gate_result=gate_from_findings(findings, fail_on), domain_result="findings" if findings else "clean",
        summary=f"{checked} infrastructure files ({scope}); {severity_summary(findings)}", findings=findings,
        details={"scope": scope, "files_checked": checked, "fail_on": fail_on,
                 "note": "Supporting signals; terraform validate/checkov/trivy/tflint via native-checks are primary."},
        started_at=started_at)
    lines = [f"check-infra: {result.summary}", *format_findings(findings)]
    if not checked:
        lines.append("  no Terraform/CloudFormation/IAM policy files in scope; use --paths or --all")
    return emit_result(args, repo_root, result, lines)
