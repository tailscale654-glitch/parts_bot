"""part_overrides: правки детали администратором (модели, категория, скрыть, фото, описание)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column("models", sa.Text(), nullable=False, server_default=""),
        sa.Column("node_ru", sa.String(128)),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("photo", sa.String(512)),
        sa.Column("description_ru", sa.Text()),
        sa.Column("description_uz", sa.Text()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("part_overrides")
