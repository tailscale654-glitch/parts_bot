"""users.blocked + part_translations (переводы названий деталей из веб-панели)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "part_translations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),  # part_name_key(английское название)
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("name_ru", sa.String(255)),
        sa.Column("name_uz", sa.String(255)),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("part_translations")
    op.drop_column("users", "blocked")
