"""ТО: пробег клиента, когда спрашивали и о каком ТО напомнили; история пробега

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("car_mileage", sa.Integer()))
    op.add_column("users", sa.Column("car_mileage_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mileage_asked_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("service_reminded_km", sa.Integer()))
    op.create_table(
        "mileage_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("km", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mileage_records_user_id", "mileage_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mileage_records_user_id", "mileage_records")
    op.drop_table("mileage_records")
    for column in ("service_reminded_km", "mileage_asked_at", "car_mileage_at", "car_mileage"):
        op.drop_column("users", column)
