"""Номер двигателя и комплектация CarSale у автомобиля клиента (подтягиваются из CarSale CRM по VIN)

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("car_engine", sa.String(32)))
    op.add_column("users", sa.Column("car_trim", sa.String(64)))


def downgrade() -> None:
    op.drop_column("users", "car_trim")
    op.drop_column("users", "car_engine")
