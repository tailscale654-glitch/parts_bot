"""Автомобиль клиента (модель, модификация, цвет), модификации деталей, автомобиль в заказе

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("car_model", sa.String(128)))
    op.add_column("users", sa.Column("car_modification", sa.String(32)))
    op.add_column("users", sa.Column("car_color", sa.String(16)))
    op.add_column("parts", sa.Column("mod_codes", sa.String(255), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("car", sa.String(128)))


def downgrade() -> None:
    op.drop_column("orders", "car")
    op.drop_column("parts", "mod_codes")
    op.drop_column("users", "car_color")
    op.drop_column("users", "car_modification")
    op.drop_column("users", "car_model")
