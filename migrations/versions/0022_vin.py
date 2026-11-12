"""VIN автомобиля клиента (профиль в витрине: сканирование или ввод)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("car_vin", sa.String(17)))


def downgrade() -> None:
    op.drop_column("users", "car_vin")
