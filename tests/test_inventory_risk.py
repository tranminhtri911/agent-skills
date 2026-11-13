"""inspect (context map), feature matching and risk suggestion on a fixture repository."""

import json
import unittest

from devskills.inventory import classify_role, feature_pattern
from devskills.risk import suggest_risk
from tests._support import commit_all, init_git_repo, make_temp_dir, run_cli, run_cli_json, write


def build_fixture(root):
    write(root, "package.json", json.dumps({
        "scripts": {"test": "vitest", "lint": "eslint ."},
        "dependencies": {"react": "^19.0.0", "next": "15.1.0", "@prisma/client": "6.0.0"},
        "devDependencies": {"vitest": "^2.1.0"},
    }))
    write(root, "pyproject.toml", '[project]\nname = "shop"\ndependencies = ["fastapi>=0.115", "sqlalchemy>=2.0"]\n[tool.pytest.ini_options]\naddopts = "-q"\n')
    write(root, "docker-compose.yml", "services:\n  db:\n    image: postgres:16.4\n")
    write(root, "CLAUDE.md", "# rules\n")
    write(root, "db/migrations/001_orders.sql", "CREATE TABLE orders (id bigint PRIMARY KEY, total_minor bigint NOT NULL);\n")
    write(root, "backend/orders/service.py", (
        "class OrderService:\n"
        "    def create_order(self, cart):\n"
        "        return cart\n"))
    write(root, "backend/orders/router.py", (
        "from backend.orders.service import OrderService\n"
        "def post_order(cart):\n"
        "    return OrderService().create_order(cart)\n"))
    write(root, "frontend/src/features/orders/OrderPage.tsx", "export function OrderPage() { return <div>Order</div>; }\n")
    write(root, "frontend/src/styles.css", ".border { border: 1px solid; }\n")
    write(root, "tests/test_orders.py", "def test_create_order():\n    assert True\n")
    write(root, ".env", "DATABASE_PASSWORD=marker-never-read-123\n")


class FeaturePatternTest(unittest.TestCase):
    def test_variants_and_boundaries(self):
        pattern = feature_pattern(["order item"])
        for text in ("order_item", "orderItem", "OrderItemService", "order-items", "ORDER_ITEM", "order items"):
            self.assertTrue(pattern.search(text), text)
        single = feature_pattern(["order"])
        self.assertFalse(single.search("border: 1px"))
        self.assertFalse(single.search("SELECT 1 ORDER BY id"))
        self.assertTrue(single.search("createOrder()"))
        self.assertTrue(feature_pattern(["category"]).search("categories"))

    def test_roles(self):
        self.assertEqual(classify_role("backend/orders/router.py"), "route")
        self.assertEqual(classify_role("tests/test_orders.py"), "test")
        self.assertEqual(classify_role("db/migrations/001.sql"), "migration")
        self.assertEqual(classify_role("frontend/src/components/Button.tsx"), "component")


class InspectTest(unittest.TestCase):
    def test_context_map(self):
        repo = make_temp_dir(self)
        init_git_repo(repo)
        build_fixture(repo)
        commit_all(repo)
        code, record = run_cli_json("inspect", "--repo", str(repo), "--feature", "order")
        self.assertEqual(code, 0, record)
        context = json.loads((repo / ".devskills" / "context" / "context-map.json").read_text())
        names = {item["name"] for items in context["stack"]["by_category"].values() for item in items}
        self.assertTrue({"FastAPI", "SQLAlchemy", "React", "Next.js", "Prisma Client", "Vitest"} <= names, names)
        self.assertEqual(context["stack"]["database_engines"][0]["engine"], "postgres")
        self.assertIn("npm run test", context["stack"]["test_commands"])
        self.assertIn("CLAUDE.md", context["instructions_to_read_first"])
        paths = [item["path"] for item in context["feature"]["files"]]
        self.assertIn("backend/orders/service.py", paths)
        self.assertNotIn("frontend/src/styles.css", paths, "`border` must not match the feature `order`")
        symbols = {symbol["name"]: symbol for symbol in context["feature"]["symbols"]}
        self.assertIn("OrderService", symbols)
        self.assertTrue(any(caller["path"] == "backend/orders/router.py" for caller in symbols["OrderService"]["callers"]))
        tables = [entity["name"] for entity in context["feature"]["db_entities"] if entity["matches_feature"]]
        self.assertIn("orders", tables)
        self.assertIn(".env", context["secret_files_not_read"])
        self.assertNotIn("marker-never-read-123", json.dumps(context))
        self.assertIn("tests/test_orders.py", context["feature"]["related_tests"])
        self.assertTrue((repo / ".devskills" / "context" / "context-map.md").read_text().startswith("# Context map"))

    def test_records_into_run(self):
        repo = make_temp_dir(self)
        build_fixture(repo)
        _code, started = run_cli_json("run", "start", "--repo", str(repo))
        completed = run_cli("inspect", "--repo", str(repo), "--feature", "order", "--run", started["run_id"])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_dir = repo / ".devskills" / "runs" / started["run_id"]
        self.assertTrue((run_dir / "checks" / "context.map.json").is_file())
        self.assertTrue((run_dir / "artifacts" / "context-map.json").is_file())


class SubdirectoryRepoTest(unittest.TestCase):
    """`--repo` may point at a package inside a bigger git work tree (monorepo, nested project)."""

    def test_changed_files_are_limited_and_relative(self):
        from devskills.fsutil import changed_files, git_status_entries

        top = make_temp_dir(self)
        init_git_repo(top)
        write(top, "pkg/api/app.py", "x = 1\n")
        write(top, "other/service.py", "y = 1\n")
        commit_all(top)
        write(top, "pkg/api/app.py", "def f(items=[]):\n    return items\n")
        write(top, "pkg/api/new.py", "z = 1\n")
        write(top, "other/service.py", "y = 2\n")
        package = top / "pkg" / "api"
        self.assertEqual(sorted(changed_files(package)), ["app.py", "new.py"])
        self.assertEqual({entry["path"] for entry in git_status_entries(package)}, {"app.py", "new.py"})
        code, payload = run_cli_json("check-code", "--repo", str(package))
        self.assertEqual(code, 3)
        self.assertEqual({finding["path"] for finding in payload["findings"]}, {"app.py"})


class RiskTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(suggest_risk(["README.md"], "", {})[0], "R0")
        self.assertEqual(suggest_risk(["src/format.py"], "+    return name.title()", {})[0], "R1")
        self.assertEqual(suggest_risk(["db/migrations/002_add.sql"], "+ALTER TABLE x ADD y int", {})[0], "R2")
        level, reasons = suggest_risk(["src/checkout.py"], "+    refund(amount_minor)", {})
        self.assertEqual(level, "R3")
        self.assertTrue(any("money/payment" in reason for reason in reasons))

    def test_cli_reads_untracked_files(self):
        repo = make_temp_dir(self)
        init_git_repo(repo)
        write(repo, "README.md", "hi\n")
        commit_all(repo)
        write(repo, "billing/refunds.py", "def refund_payment(payment_id):\n    return payment_id\n")
        code, payload = run_cli_json("risk", "--repo", str(repo))
        self.assertEqual((code, payload["suggested_risk"]), (0, "R3"))


if __name__ == "__main__":
    unittest.main()
