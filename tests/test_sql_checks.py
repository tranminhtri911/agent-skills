"""check-sql: masking, destructive statements, schema rules, FK policy, index builds, ORM foreign keys."""

import unittest

from devskills.sql_checks import check_orm_foreign_keys, check_sql_text, mask_sql, split_statements


def sql_rules(text, engine="postgresql", fk_policy="discouraged", path="db/migrations/001.sql"):
    return [(finding.rule_id, finding.severity) for finding in
            check_sql_text(path, text, engine, fk_policy, ["idx_", "ix_"], ["uq_", "ux_"])]


def ids(text, **kwargs):
    return [rule for rule, _ in sql_rules(text, **kwargs)]


class MaskingTest(unittest.TestCase):
    def test_comments_strings_and_dollar_bodies_are_masked(self):
        text = ("-- DELETE FROM users;\nSELECT 'DELETE FROM x; ok' AS note;\n"
                "CREATE FUNCTION f() RETURNS void AS $$ BEGIN DELETE FROM audit; END $$ LANGUAGE plpgsql;\n")
        masked, comments = mask_sql(text)
        self.assertEqual(text.count("\n"), masked.count("\n"))
        statements = split_statements(masked)
        self.assertEqual(len(statements), 2)
        self.assertEqual(statements[1].start_line, 3)
        self.assertEqual(len(comments), 1)
        self.assertNotIn("SQL-DELETE-WITHOUT-WHERE", ids(text))


class DestructiveStatementTest(unittest.TestCase):
    def test_delete_update_without_where(self):
        found = sql_rules("DELETE FROM orders;\nUPDATE orders SET status = 'x';\nDELETE FROM orders WHERE id = 1;\n")
        self.assertIn(("SQL-DELETE-WITHOUT-WHERE", "critical"), found)
        self.assertIn(("SQL-UPDATE-WITHOUT-WHERE", "critical"), found)
        self.assertEqual([rule for rule, _ in found].count("SQL-DELETE-WITHOUT-WHERE"), 1)

    def test_drop_truncate_rename(self):
        rules = ids("DROP TABLE legacy;\nTRUNCATE audit;\nALTER TABLE users RENAME COLUMN name TO full_name;\n"
                    "ALTER TABLE users DROP COLUMN age;\n")
        for expected in ("SQL-DROP", "SQL-TRUNCATE", "SQL-RENAME", "SQL-DROP-COLUMN"):
            self.assertIn(expected, rules)


class SchemaRulesTest(unittest.TestCase):
    def test_primary_key_money_and_naming(self):
        found = sql_rules("CREATE TABLE OrderItems (sku text, unit_price double precision, quantity int);\n")
        self.assertIn(("SQL-NO-PRIMARY-KEY", "high"), found)
        self.assertIn(("SQL-FLOAT-MONEY", "high"), found)
        self.assertIn(("SQL-TABLE-NAMING", "low"), found)
        clean = ids("CREATE TABLE order_items (id bigint PRIMARY KEY, unit_price_minor bigint NOT NULL, "
                    "created_at timestamptz NOT NULL DEFAULT now());\n")
        self.assertEqual(clean, [])

    def test_foreign_key_policy(self):
        statement = "CREATE TABLE items (id bigint PRIMARY KEY, order_id bigint REFERENCES orders(id), created_at timestamptz);\n"
        self.assertIn(("SQL-FOREIGN-KEY", "medium"), sql_rules(statement, fk_policy="discouraged"))
        self.assertIn(("SQL-FOREIGN-KEY", "high"), sql_rules(statement, fk_policy="forbidden"))
        self.assertNotIn("SQL-FOREIGN-KEY", ids(statement, fk_policy="allowed"))
        self.assertIn("SQL-FOREIGN-KEY", ids("ALTER TABLE items ADD CONSTRAINT fk_o FOREIGN KEY (order_id) REFERENCES orders(id);\n"))

    def test_not_null_without_default_on_existing_table(self):
        self.assertIn("SQL-ADD-NOT-NULL-NO-DEFAULT", ids("ALTER TABLE users ADD COLUMN tier text NOT NULL;\n"))
        self.assertNotIn("SQL-ADD-NOT-NULL-NO-DEFAULT", ids("ALTER TABLE users ADD COLUMN tier text NOT NULL DEFAULT 'basic';\n"))

    def test_index_builds_on_postgresql(self):
        existing = ids("CREATE INDEX idx_orders_status ON orders (status);\n")
        self.assertIn("SQL-INDEX-BLOCKS-WRITES", existing)
        same_file = ids("CREATE TABLE t (id bigint PRIMARY KEY, created_at timestamptz);\nCREATE INDEX idx_t_created ON t (created_at);\n")
        self.assertNotIn("SQL-INDEX-BLOCKS-WRITES", same_file)
        concurrent = ids("CREATE INDEX CONCURRENTLY idx_orders_tenant ON orders (tenant_id);\n")
        self.assertIn("SQL-INDEX-CONCURRENTLY", concurrent)
        self.assertNotIn("SQL-INDEX-BLOCKS-WRITES", concurrent)
        self.assertIn("SQL-INDEX-NAMING", ids("CREATE UNIQUE INDEX orders_number ON orders (number);\n"))
        self.assertNotIn("SQL-INDEX-BLOCKS-WRITES", ids("CREATE INDEX idx_a ON orders (a);\n", engine="mysql"))

    def test_key_ddl_on_existing_table_needs_online_form(self):
        blocking = sql_rules("SET lock_timeout = '3s';\nALTER TABLE orders ADD CONSTRAINT uq_orders_number UNIQUE (number);\n"
                             "ALTER TABLE orders ADD PRIMARY KEY (id);\n")
        self.assertEqual([rule for rule, _ in blocking].count("SQL-KEY-DDL-BLOCKING"), 2)
        self.assertNotIn("SQL-KEY-DDL-NO-LOCK-TIMEOUT", [rule for rule, _ in blocking])
        online = ids("SET lock_timeout = '3s';\nALTER TABLE orders ADD CONSTRAINT orders_pkey PRIMARY KEY USING INDEX uq_orders_id;\n")
        self.assertEqual(online, [])
        new_table = ids("CREATE TABLE t (id bigint PRIMARY KEY, n text, created_at timestamptz);\n"
                        "ALTER TABLE t ADD CONSTRAINT uq_t_n UNIQUE (n);\n")
        self.assertNotIn("SQL-KEY-DDL-BLOCKING", new_table)
        self.assertNotIn("SQL-KEY-DDL-NO-LOCK-TIMEOUT", new_table)
        mysql = "ALTER TABLE orders ADD UNIQUE KEY uq_orders_number (number){};\n"
        self.assertIn("SQL-KEY-DDL-BLOCKING", ids(mysql.format(""), engine="mysql"))
        self.assertNotIn("SQL-KEY-DDL-BLOCKING", ids(mysql.format(", ALGORITHM=INPLACE, LOCK=NONE"), engine="mysql"))

    def test_foreign_key_without_not_valid(self):
        statement = "ALTER TABLE items ADD CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id){};\n"
        self.assertIn("SQL-FK-VALIDATES-UNDER-LOCK", ids(statement.format(""), fk_policy="allowed"))
        self.assertNotIn("SQL-FK-VALIDATES-UNDER-LOCK", ids(statement.format(" NOT VALID"), fk_policy="allowed"))

    def test_key_type_change(self):
        found = sql_rules("ALTER TABLE orders ALTER COLUMN id TYPE bigint;\nALTER TABLE items ALTER COLUMN order_id SET DATA TYPE bigint;\n"
                          "ALTER TABLE orders ALTER COLUMN note TYPE text;\n")
        self.assertEqual(found.count(("SQL-KEY-TYPE-CHANGE", "high")), 2)
        self.assertEqual([rule for rule, _ in found].count("SQL-ALTER-TYPE"), 1)
        self.assertIn("SQL-KEY-TYPE-CHANGE", ids("ALTER TABLE orders MODIFY COLUMN customer_id BIGINT NOT NULL;\n", engine="mysql"))

    def test_key_ddl_without_lock_timeout(self):
        found = sql_rules("ALTER TABLE orders VALIDATE CONSTRAINT fk_orders_customer;\nALTER TABLE orders DROP CONSTRAINT uq_old;\n")
        self.assertEqual(found.count(("SQL-KEY-DDL-NO-LOCK-TIMEOUT", "medium")), 1)
        late = ids("ALTER TABLE orders DROP CONSTRAINT uq_old;\nSET lock_timeout = '3s';\n")
        self.assertIn("SQL-KEY-DDL-NO-LOCK-TIMEOUT", late)
        self.assertNotIn("SQL-KEY-DDL-NO-LOCK-TIMEOUT",
                         ids("SET SESSION lock_wait_timeout = 3;\nALTER TABLE orders DROP INDEX uq_old;\n", engine="mysql"))
        self.assertNotIn("SQL-KEY-DDL-NO-LOCK-TIMEOUT", ids("ALTER TABLE orders ADD COLUMN note text;\n"))
        self.assertNotIn("SQL-DROP-COLUMN", ids("ALTER TABLE orders DROP PRIMARY KEY, DROP FOREIGN KEY fk_a;\n", engine="mysql"))

    def test_multiline_dash_comments(self):
        self.assertIn("SQL-MULTILINE-COMMENT", ids("-- one\n-- two\n-- three\nSELECT 1;\n"))


class OrmForeignKeyTest(unittest.TestCase):
    def test_orm_patterns_and_disabled_markers(self):
        django = "class Item(models.Model):\n    order = models.ForeignKey(Order, on_delete=models.PROTECT)\n"
        self.assertEqual(len(check_orm_foreign_keys("app/models.py", django, "discouraged")), 1)
        no_constraint = "    order = models.ForeignKey(Order, on_delete=models.PROTECT, db_constraint=False)\n"
        self.assertEqual(check_orm_foreign_keys("app/models.py", no_constraint, "discouraged"), [])
        laravel = "$table->foreignId('order_id')->constrained();\n"
        self.assertEqual(len(check_orm_foreign_keys("database/migrations/x.php", laravel, "discouraged")), 1)
        prisma = 'datasource db {\n  relationMode = "prisma"\n}\nmodel Item {\n  order Order @relation(fields: [orderId], references: [id])\n}\n'
        self.assertEqual(check_orm_foreign_keys("prisma/schema.prisma", prisma, "discouraged"), [])
        self.assertEqual(check_orm_foreign_keys("app/models.py", django, "allowed"), [])


if __name__ == "__main__":
    unittest.main()
