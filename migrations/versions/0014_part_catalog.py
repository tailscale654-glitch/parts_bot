"""part_catalog: справочник запчастей завода (артикул → модели, название)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column("models", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("part_catalog")
