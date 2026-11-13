"""CODE-011 values and DES-007 patterns: what the source already defines is found and reused."""

import unittest

from devskills.conventions import detect_conventions, pattern_tools, patterns_in_use
from devskills.domain_values import RULE_ID, collect_domain_values, hardcoded_value_findings
from tests._support import make_temp_dir, run_cli_json, write

SOURCES = {
    "orders/models.py": (
        "from django.db import models\n\n"
        "class OrderStatus(models.TextChoices):\n"
        '    PENDING = "pending", _("Pending")\n'
        '    PAID = "paid", _("Paid")\n'
        '    CANCELLED = "cancelled"\n\n'
        "class Order(models.Model):\n"
        "    status = models.CharField(choices=OrderStatus.choices)\n"),
    "core/param_key.py": 'USER_ID = "user_id"\nUSER_NAME = "user_name"\nUSER_LIST = "user_list"\n',
    "web/src/constants/order.ts": "export const OrderStatus = {\n  Pending: 'pending',\n  Paid: 'paid',\n} as const;\n"
                                  "export enum Role { Admin = 'admin', Staff = 'staff' }\n",
    "app/Enums/Facility.php": "<?php\nenum Facility: string {\n    case SBF = 'sbf';\n    case KBF = 'kbf';\n}\n",
    "Domain/OrderState.cs": "public enum OrderState\n{\n    [Display(Name = \"x\")]\n    Draft = 0,\n    Submitted, // sent\n}\n",
}


def findings_for(path: str, text: str) -> list:
    return hardcoded_value_findings(path, text, collect_domain_values(SOURCES))


class CollectTest(unittest.TestCase):
    def test_value_sets_per_language(self):
        sets = {(item.family, item.name): item for item in collect_domain_values(SOURCES)}
        self.assertEqual(sets[("python", "OrderStatus")].members["paid"], "OrderStatus.PAID")
        self.assertEqual(sets[("js", "OrderStatus")].members["pending"], "OrderStatus.Pending")
        self.assertEqual(sets[("js", "Role")].members["admin"], "Role.Admin")
        self.assertEqual(sets[("php", "Facility")].members["sbf"], "Facility::SBF")
        self.assertEqual(set(sets[("csharp", "OrderState")].members), {"Draft", "Submitted"})
        self.assertEqual(sets[("python", "USER_*")].kind, "keys", "name-mirroring constants are field names, not values")

    def test_inspect_lists_values_for_the_feature_first(self):
        conventions = detect_conventions(SOURCES, ["orders/views.py"])
        names = [item["name"] for item in conventions["domain_values"]]
        self.assertIn("OrderStatus", names)
        self.assertIn("Facility", names)


class FindingsTest(unittest.TestCase):
    def test_python_comparison_query_and_membership(self):
        code = ('def f(order, qs, s):\n'
                '    if order.status == "pending":\n'
                '        qs.filter(status="paid")\n'
                '    if s in ("paid", "cancelled"):\n'
                '        pass\n')
        found = {(item.line, item.severity) for item in findings_for("orders/views.py", code)}
        self.assertEqual(found, {(2, "medium"), (3, "medium"), (4, "low")})

    def test_quiet_cases(self):
        quiet = ('def f(row, user_ids):\n'
                 '    """Example: {"status": "pending"}"""\n'
                 '    label = "paid"\n'
                 '    log("pending items")\n'
                 '    name = row["user_id"]\n'
                 '    PENDING_ALIAS = "pending"\n'
                 '    return {"user_id": 1}  # "paid"\n')
        self.assertEqual(findings_for("orders/views.py", quiet), [])
        self.assertEqual(findings_for("orders/tests/test_views.py", 'assert data["status"] == "paid"\n'), [])
        self.assertEqual(findings_for("orders/migrations/0002.py", 'Order.objects.filter(status="paid")\n'), [])
        self.assertEqual(findings_for("database/factories/OrderFactory.php", "<?php\n'facility' => 'sbf',\n"), [])

    def test_other_languages(self):
        tsx = findings_for("web/src/pages/Orders.tsx", "if (order.status === 'paid') {}\nconst isAdmin = user.role === 'admin';\n")
        self.assertEqual([item.line for item in tsx], [1, 2])
        self.assertIn("OrderStatus.Paid", tsx[0].message)
        php = findings_for("app/Http/Controllers/BookingController.php", "<?php\n$q->where('facility', 'sbf');\n")
        self.assertIn("Facility::SBF", php[0].hint)
        cs = findings_for("Web/OrdersController.cs", 'if (o.State.ToString() == "Submitted") { }\n')
        self.assertEqual(cs[0].rule_id, RULE_ID)
        # A Python literal never matches a TS enum: families do not mix.
        self.assertEqual(findings_for("orders/api.py", 'if role == "admin":\n    pass\n'), [])

    def test_check_code_reports_and_honours_suppression_and_profile(self):
        repo = make_temp_dir(self)
        for path, text in SOURCES.items():
            write(repo, path, text)
        write(repo, "orders/views.py", 'def f(order):\n    return order.status == "paid"\n')
        code, payload = run_cli_json("check-code", "--repo", str(repo), "--paths", "orders/views.py")
        self.assertEqual((code, payload["gate_result"]), (0, "warn"))
        self.assertEqual([item["rule_id"] for item in payload["findings"]], [RULE_ID])
        write(repo, "orders/views.py", 'def f(order):\n    return order.status == "paid"  '
                                       '# devskills:ignore GEN-HARDCODED-DOMAIN-VALUE external webhook value\n')
        _, payload = run_cli_json("check-code", "--repo", str(repo), "--paths", "orders/views.py")
        self.assertEqual(payload["gate_result"], "pass")
        write(repo, "orders/views.py", 'def f(order):\n    return order.status == "paid"\n')
        write(repo, ".devskills.toml", "[code]\nhardcoded_values = false\n")
        _, payload = run_cli_json("check-code", "--repo", str(repo), "--paths", "orders/views.py")
        self.assertEqual(payload["gate_result"], "pass")



class PatternsInUseTest(unittest.TestCase):
    def test_roles_from_class_names_and_python_modules_skip_tests(self):
        source = {
            "app/Services/Booking/BookingService.php": "<?php\nclass BookingService {}\n",
            "app/Services/Pdf/PdfService.php": "<?php\nclass PdfService {}\n",
            "app/Http/Requests/StoreBookingRequest.php": "<?php\nclass StoreBookingRequest extends FormRequest {}\n",
            "orders/selectors.py": "def open_orders(): ...\n",
            "invoices/selectors.py": "def unpaid(): ...\n",
            "tests/Feature/FakeService.php": "<?php\nclass FakeService {}\nclass OtherService {}\n",
        }
        roles = {item["role"]: item for item in patterns_in_use(source)}
        self.assertEqual(roles["Service"]["count"], 2, "test doubles are not the project's architecture")
        self.assertEqual(set(roles["Service"]["where"]), {"app/Services/Booking", "app/Services/Pdf"})
        self.assertEqual(roles["selectors.py"]["count"], 2)
        self.assertNotIn("Request", roles, "a single occurrence is not a pattern yet")

    def test_pattern_libraries_and_configs(self):
        files = {
            "composer.json": '{"require": {"spatie/laravel-model-states": "^2.7", "laravel/framework": "^11"}}',
            "web/package.json": '{"dependencies": {"@tanstack/react-query": "5.0.0", "swrve": "1"}}',
            "deptrac.yaml": "deptrac:\n  layers: []\n",
            "README.md": "We might try xstate later.",
        }
        found = {item["name"]: item["kind"] for item in pattern_tools(files)}
        self.assertEqual(found, {"spatie/laravel-model-states": "state machine", "@tanstack/react-query": "server-state cache",
                                 "deptrac.yaml": "layer rules"})


if __name__ == "__main__":
    unittest.main()
