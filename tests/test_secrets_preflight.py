"""Secret detection/redaction and environment preflight classification."""

import unittest

from devskills.preflight import classify_host, compose_service_names, evaluate_environment, parse_dotenv
from devskills.secrets_scan import redact_text, scan_text
from tests._support import fake_secret, make_temp_dir, run_cli, write


class SecretScanTest(unittest.TestCase):
    def test_detects_and_redacts(self):
        live_key = fake_secret("sk_" + "live_")
        aws_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        text = (f"STRIPE_KEY = '{live_key}'\n"
                f"aws_id = '{aws_key}'\n"
                "-----BEGIN RSA " + "PRIVATE KEY-----\n"
                "DATABASE_URL=postgres://app:" + "S3cretPassw0rd" + "@db.example.com/app\n"
                "LOCAL_URL=postgres://app:" + "localpass1" + "@localhost/app\n"
                "password = 'changeme'\n")
        findings, suppressed = scan_text(text, "config.py")
        rules = {(finding.rule_id, finding.severity) for finding in findings}
        self.assertIn(("SECRET-STRIPE-LIVE-KEY", "critical"), rules)
        self.assertIn(("SECRET-AWS-ACCESS-KEY", "high"), rules)
        self.assertIn(("SECRET-PRIVATE-KEY", "critical"), rules)
        self.assertIn(("SECRET-URL-CREDENTIALS", "high"), rules)
        self.assertIn(("SECRET-URL-CREDENTIALS", "low"), rules)
        self.assertFalse(any("changeme" in finding.message for finding in findings), "placeholders are not findings")
        for finding in findings:
            self.assertNotIn(live_key, finding.message)
        self.assertEqual(suppressed, [])

    def test_allow_marker_needs_reason(self):
        token = fake_secret("ghp_", 36)
        with_reason = f"token = '{token}'  # devskills:allow-secret revoked fixture token\n"
        without_reason = f"token = '{token}'  # devskills:allow-secret\n"
        self.assertEqual(len(scan_text(with_reason, "a.py")[1]), 1)
        self.assertEqual(len(scan_text(without_reason, "a.py")[0]), 1)

    def test_redact_text_hides_values(self):
        key = fake_secret("sk_" + "live_")
        redacted = redact_text(f"error calling provider with {key}")
        self.assertNotIn(key, redacted)
        self.assertIn("chars]", redacted)

    def test_cli_reports_tracked_env_file_without_reading_it(self):
        from tests._support import commit_all, init_git_repo

        repo = make_temp_dir(self)
        init_git_repo(repo)
        write(repo, ".env", "SECRET_MARKER_VALUE=do-not-read\n")
        commit_all(repo)
        completed = run_cli("scan-secrets", "--repo", str(repo), "--all", "--json")
        self.assertEqual(completed.returncode, 3)
        self.assertIn("SECRET-TRACKED-SECRET-FILE", completed.stdout)
        self.assertNotIn("do-not-read", completed.stdout)


class PreflightTest(unittest.TestCase):
    def test_host_classification(self):
        self.assertEqual(classify_host("localhost", set(), set()), "local")
        self.assertEqual(classify_host("127.0.0.1", set(), set()), "local")
        self.assertEqual(classify_host("db", set(), {"db"}), "compose")
        self.assertEqual(classify_host("db", set(), set()), "remote", "a bare name outside compose may resolve via DNS search domains")
        self.assertEqual(classify_host("10.0.0.5", set(), set()), "remote")
        self.assertEqual(classify_host("10.0.0.5", {"10.0.0.5"}, set()), "allowed")
        self.assertEqual(classify_host("prod-db.internal", {"prod-db.internal"}, set()), "production")
        self.assertEqual(classify_host("api.sandbox.test", set(), set()), "local")

    def test_environment_decisions(self):
        variables = {
            "STRIPE_SECRET_KEY": fake_secret("sk_" + "live_"),
            "APP_ENV": "production",
            "DATABASE_URL": "postgresql://u:p@orders-db.example.com:5432/orders",  # devskills:allow-secret fake fixture credential for preflight tests
            "REDIS_URL": "redis://localhost:6379/0",
            "SENDGRID_API_KEY": "SG.fake",
            "AWS_ACCESS_KEY_ID": "AKIA-fake",
        }
        decision = evaluate_environment([(".env.test", variables)], set(), set())
        rules = {finding.rule_id for finding in decision.findings}
        self.assertTrue(decision.blocked)
        self.assertTrue({"SAFE-005-LIVE-KEY", "SAFE-001-PRODUCTION-ENV", "SAFE-002-REMOTE-TARGET",
                         "SAFE-005-PROVIDER-CREDENTIAL", "SAFE-005-CLOUD-CREDENTIAL"} <= rules)
        self.assertFalse(any("REDIS_URL" in (finding.path or "") for finding in decision.findings))
        for finding in decision.findings:
            self.assertNotIn("u:p@", finding.message, "credentials inside URLs are never printed")

    def test_safe_environment_passes(self):
        decision = evaluate_environment([(".env.test", {"DATABASE_URL": "postgres://u:p@localhost/test", "APP_ENV": "test"})], set(), set())  # devskills:allow-secret fake fixture credential for preflight tests
        self.assertFalse(decision.blocked)

    def test_parse_dotenv_and_compose_services(self):
        parsed = parse_dotenv("# c\nexport A=1\nB=\"two words\"\nC='x' \nD=value # trailing\n")
        self.assertEqual(parsed, {"A": "1", "B": "two words", "C": "x", "D": "value"})
        repo = make_temp_dir(self)
        write(repo, "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\nvolumes:\n  data: {}\n")
        self.assertEqual(compose_service_names(repo), {"db", "cache"})

    def test_cli_blocks_and_requires_reason_for_ignored_files(self):
        repo = make_temp_dir(self)
        write(repo, ".env", "DATABASE_URL=postgres://u:p@prod-db.example.com/app\n")  # devskills:allow-secret fake fixture credential for preflight tests
        blocked = run_cli("preflight", "--repo", str(repo))
        self.assertEqual(blocked.returncode, 4, blocked.stdout)
        missing_reason = run_cli("preflight", "--repo", str(repo), "--dotenv-not-loaded", ".env")
        self.assertEqual(missing_reason.returncode, 2)
        allowed = run_cli("preflight", "--repo", str(repo), "--dotenv-not-loaded", ".env", "--reason", "tests use .env.testing only")
        self.assertIn(allowed.returncode, (0,), allowed.stdout)


if __name__ == "__main__":
    unittest.main()
