"""Фото деталей из электронного каталога JAC (EPC): картинки и связь «артикул → картинка»

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "epc_images",
        sa.Column("md5", sa.String(32), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "epc_photos",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column("image", sa.String(32), sa.ForeignKey("epc_images.md5", ondelete="CASCADE"), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("epc_photos")
    op.drop_table("epc_images")
