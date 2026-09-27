"""dealer directory: code, name_key, enabled, in_directory

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.utils.names import dealer_key

    op.add_column("dealers", sa.Column("name_key", sa.String(255)))
    op.add_column("dealers", sa.Column("code", sa.String(32)))
    op.add_column("dealers", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("dealers", sa.Column("in_directory", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Заполняем ключи для уже загруженных дилеров. Если два дилера дали один ключ —
    # оставляем один, цены второго переносим на него.
    conn = op.get_bind()
    by_key: dict[str, int] = {}
    for dealer_id, name in conn.execute(sa.text("SELECT id, name FROM dealers ORDER BY id")).all():
        key = dealer_key(name) or f"dealer{dealer_id}"
        if key in by_key:
            keep = by_key[key]
            conn.execute(sa.text(
                "DELETE FROM stocks WHERE dealer_id = :d AND part_id IN (SELECT part_id FROM stocks WHERE dealer_id = :k)"
            ), {"d": dealer_id, "k": keep})
            conn.execute(sa.text("UPDATE stocks SET dealer_id = :k WHERE dealer_id = :d"), {"d": dealer_id, "k": keep})
            conn.execute(sa.text("DELETE FROM dealers WHERE id = :d"), {"d": dealer_id})
            continue
        by_key[key] = dealer_id
        conn.execute(sa.text("UPDATE dealers SET name_key = :k WHERE id = :d"), {"k": key, "d": dealer_id})

    op.alter_column("dealers", "name_key", nullable=False)
    op.drop_constraint("uq_dealers_region_name", "dealers", type_="unique")
    op.create_unique_constraint("uq_dealers_name_key", "dealers", ["name_key"])


def downgrade() -> None:
    op.drop_constraint("uq_dealers_name_key", "dealers", type_="unique")
    op.create_unique_constraint("uq_dealers_region_name", "dealers", ["region_id", "name"])
    op.drop_column("dealers", "in_directory")
    op.drop_column("dealers", "enabled")
    op.drop_column("dealers", "code")
    op.drop_column("dealers", "name_key")
