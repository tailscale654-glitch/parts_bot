"""Источник фото детали: каталог JAC (epc) или свой магазин jac-zap.ru — настоящее фото главнее рисунка

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("epc_photos", sa.Column("source", sa.String(16), nullable=False, server_default="epc"))


def downgrade() -> None:
    op.drop_column("epc_photos", "source")
