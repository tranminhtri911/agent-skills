"""check-infra rules (IAM least privilege, private network, data/compute), Terraform native planning, roster and guard."""

import unittest
from unittest import mock

from devskills.guard import evaluate_command
from devskills.infra_checks import check_infra_file
from devskills.native import find_project_dirs, plan_checks
from devskills.runs import build_default_roster, tag_changed_paths
from tests._support import make_temp_dir, run_cli_json, write

BAD_TF = '''
resource "aws_security_group" "app" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_db_instance" "main" {
  publicly_accessible = true
  password            = "dummy_password"
}
resource "aws_instance" "web" {
  associate_public_ip_address = true
}
data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["s3:*"]
    resources = ["*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = ["*"]
  }
}
resource "aws_iam_policy" "admin" {
  policy = jsonencode({
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}
resource "aws_iam_role" "ci" {
  assume_role_policy = jsonencode({
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = "arn:aws:iam::1:oidc-provider/token.actions.githubusercontent.com" }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" } }
    }]
  })
}
resource "google_project_iam_member" "dev" {
  role   = "roles/editor"
  member = "user:dev@example.com"
}
resource "google_storage_bucket_iam_member" "public" {
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
resource "google_compute_firewall" "ssh" {
  source_ranges = ["0.0.0.0/0"]
  allow {
    protocol = "tcp"
    ports    = ["22", "80"]
  }
}
resource "google_service_account_key" "key" {}
'''

GOOD_TF = '''
resource "aws_security_group_rule" "db_from_app" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.app.id
}
resource "aws_db_instance" "main" {
  publicly_accessible         = false
  storage_encrypted           = true
  deletion_protection         = true
  manage_master_user_password = true
}
resource "aws_launch_template" "app" {
  metadata_options {
    http_tokens = "required"
  }
}
data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/tenants/*"]
  }
  statement {
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }
}
resource "aws_iam_role" "ci" {
  assume_role_policy = jsonencode({
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = "arn:aws:iam::1:oidc-provider/token.actions.githubusercontent.com" }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringLike = { "token.actions.githubusercontent.com:sub" = "repo:acme/shop:ref:refs/heads/main" } }
    }]
  })
}
resource "google_storage_bucket_iam_member" "app" {
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.app.email}"
}
'''

CFN = '''AWSTemplateFormatVersion: "2010-09-09"
Resources:
  Sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 3389
          ToPort: 3389
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort: 443
          ToPort: 443
          CidrIp: 0.0.0.0/0
  Role:
    Type: AWS::IAM::Role
    Properties:
      Policies:
        - PolicyName: p
          PolicyDocument:
            Statement:
              - Action:
                  - dynamodb:PutItem
                  - dynamodb:GetItem
                Effect: Allow
                Resource: "*"
              - Effect: Allow
                Action: s3:GetObject
                Resource: arn:aws:s3:::b/*
'''

POLICY_JSON = ('{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"},'
               ' {"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}]}')


def rules(path: str, text: str) -> set[str]:
    return {finding.rule_id for finding in check_infra_file(path, text)}


class InfraRulesTest(unittest.TestCase):
    def test_terraform_misconfigurations(self):
        found = rules("infra/main.tf", BAD_TF)
        expected = {"INF-NET-PUBLIC-ADMIN", "INF-DB-PUBLIC", "INF-DB-UNENCRYPTED", "INF-DB-PASSWORD-LITERAL", "INF-EC2-IMDSV1",
                    "INF-EC2-PUBLIC-IP", "INF-IAM-SERVICE-WILDCARD", "INF-IAM-RESOURCE-WILDCARD", "INF-IAM-PASSROLE", "INF-IAM-ADMIN",
                    "INF-IAM-OIDC-UNSCOPED", "INF-GCP-PRIMITIVE-ROLE", "INF-GCP-PUBLIC-MEMBER", "INF-IAM-LONG-LIVED-KEY"}
        self.assertEqual(expected - found, set())
        ssh = [finding for finding in check_infra_file("infra/main.tf", BAD_TF) if finding.rule_id == "INF-NET-PUBLIC-ADMIN"]
        self.assertEqual(len(ssh), 2, "AWS 22 and GCP 22; the public 443/80 rules are fine")

    def test_least_privilege_terraform_is_clean(self):
        self.assertEqual(check_infra_file("infra/main.tf", GOOD_TF), [])

    def test_cloudformation_and_policy_json(self):
        cfn = {(finding.rule_id, finding.message) for finding in check_infra_file("stack.yaml", CFN)}
        self.assertIn(("INF-IAM-RESOURCE-WILDCARD", 'write actions on Resource "*": dynamodb:putitem'), cfn)
        self.assertIn(("INF-NET-PUBLIC-ADMIN", "SecurityGroupIngress: RDP open to the internet"), cfn)
        self.assertEqual(len(cfn), 2)
        self.assertEqual(rules("policies/app.json", POLICY_JSON), {"INF-IAM-NOT-ACTION", "INF-IAM-PUBLIC-PRINCIPAL"})
        self.assertEqual(rules("package.json", '{"name": "x"}'), set())

    def test_cli_gate(self):
        repo = make_temp_dir(self)
        write(repo, "infra/main.tf", BAD_TF)
        code, payload = run_cli_json("check-infra", "--repo", str(repo), "--all")
        self.assertEqual((code, payload["gate_result"]), (3, "fail"))
        write(repo, "infra/main.tf", GOOD_TF)
        code, payload = run_cli_json("check-infra", "--repo", str(repo), "--all")
        self.assertEqual((code, payload["gate_result"]), (0, "pass"))


class TerraformNativeAndRosterTest(unittest.TestCase):
    def test_top_level_terraform_project_and_offline_plan(self):
        repo = make_temp_dir(self)
        write(repo, "infra/main.tf", GOOD_TF)
        write(repo, "infra/modules/vpc/main.tf", 'variable "cidr" {}\n')
        self.assertEqual(find_project_dirs(repo), {"infra": {".tf"}})
        with mock.patch("devskills.native.shutil.which", lambda name: f"/usr/bin/{name}" if name == "terraform" else None):
            planned = {check.check_id: check for check in plan_checks(repo, {"lint", "typecheck"})}
        self.assertEqual(planned["native.lint.infra"].argv[1:], ["fmt", "-check", "-recursive", "-diff"])
        self.assertIn("init -backend=false", planned["native.typecheck.infra"].blocked_reason)
        commands = " ".join(" ".join(check.argv) for check in planned.values())
        for forbidden in ("apply", "plan", "init", "import", "state"):
            self.assertNotIn(f" {forbidden}", commands)

    def test_roster_expects_infra_checks(self):
        tags = tag_changed_paths(["infra/rds.tf"])
        self.assertIn("infra", tags)
        roster = {item["check_id"]: item for item in build_default_roster("R2", tags, [("native.lint.infra", "lint")])}
        self.assertTrue(roster["infra.static"]["required"])
        self.assertTrue(roster["native.lint.infra"]["required"])


class GuardInfraTest(unittest.TestCase):
    def test_access_and_state_changes_ask(self):
        for command in ("aws iam attach-role-policy --role-name app --policy-arn arn:aws:iam::aws:policy/AdministratorAccess",
                        "aws s3api put-bucket-policy --bucket b --policy file://p.json",
                        "aws ec2 authorize-security-group-ingress --group-id sg-1 --cidr 0.0.0.0/0 --port 22",
                        "gcloud projects add-iam-policy-binding p --member=user:a --role=roles/editor",
                        "gcloud iam service-accounts keys create key.json --iam-account sa@p.iam.gserviceaccount.com",
                        "terraform state rm aws_db_instance.main", "tofu import aws_s3_bucket.b b"):
            self.assertEqual(evaluate_command(command)[0], "ask", command)
        for command in ("terraform fmt -check -recursive", "terraform validate", "aws iam list-roles", "gcloud compute firewall-rules list"):
            self.assertIsNone(evaluate_command(command)[0], command)


if __name__ == "__main__":
    unittest.main()
