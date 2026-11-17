# Integrity without database foreign keys (plan §14.2)

Use this reference only when the project explicitly sets `foreign_key_policy = "discouraged"` or `"forbidden"`. The suite default is `"allowed"`; existing FKs remain untouched. A missing FK moves responsibility for referential integrity into the application, so it must be designed, not assumed.

## Required for every relation without an FK

1. **Owner**: the one service/module (or controlled set) allowed to write the child table.
2. **Parent check + race**: checking "parent exists" then inserting is not enough. Use one of:
   - lock the parent row (`SELECT … FOR UPDATE` / `FOR KEY SHARE`) in the same transaction as the child insert, and have parent deletion lock the same way;
   - soft-delete parents only (never hard delete while children can be created);
   - conditional insert: `INSERT … SELECT … WHERE EXISTS (SELECT 1 FROM parent WHERE id = :id AND deleted_at IS NULL)` and check the affected rows.
3. **Delete policy**: restrict, soft delete, business cascade, or archive — and who runs it (service, worker, batch).
4. **Index** on the reference column (and composite with tenant) for lookups and deletion checks.
5. **Reconciliation**: scheduled orphan detection with alerting and a reviewed fix path.
6. **Tests**: concurrent create-child vs delete-parent, admin/import bypass paths, orphan job.

## ORM switches that keep relations without DB constraints

| ORM | Keep the relation, skip the DB FK |
| --- | --- |
| Django | `models.ForeignKey(Parent, on_delete=models.PROTECT, db_constraint=False)` |
| SQLAlchemy | `relationship(Parent, primaryjoin="Child.parent_id == foreign(Parent.id)")` with a plain indexed column |
| Alembic | do not emit `op.create_foreign_key`; add `op.create_index` on the column |
| Laravel | `$table->foreignId('order_id')->index();` (no `->constrained()`) |
| Prisma | `datasource db { relationMode = "prisma" }` + `@@index([orderId])` |
| TypeORM | `@ManyToOne(() => Order, { createForeignKeyConstraints: false })` + `@Index()` |
| Sequelize | `Item.belongsTo(Order, { constraints: false })` |
| JPA/Hibernate | `@JoinColumn(name = "order_id", foreignKey = @ForeignKey(ConstraintMode.NO_CONSTRAINT))` |
| Rails | `t.references :order, index: true, foreign_key: false` |
| EF Core | configure the relationship and remove the generated FK from the migration (review carefully) |

`ds.py check-sql` reports new FKs in SQL and ORM code with the matching hint.

## When to argue for an FK anyway

Ledgers, money movements, permissions and anything where an orphan is a correctness or security bug. Present the tradeoff (integrity guarantee vs write cost, migration flexibility, sharding plans) and let the user decide.
