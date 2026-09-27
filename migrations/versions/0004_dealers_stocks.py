"""dealers and stocks (prices / quantities)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dealers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("address", sa.String(512)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("region_id", "name", name="uq_dealers_region_name"),
    )
    op.create_index("ix_dealers_region_id", "dealers", ["region_id"])
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dealer_id", sa.Integer(), sa.ForeignKey("dealers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_days", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("part_id", "dealer_id", name="uq_stocks_part_dealer"),
        sa.CheckConstraint("price >= 0", name="ck_stocks_price"),
        sa.CheckConstraint("quantity >= 0", name="ck_stocks_quantity"),
    )
    op.create_index("ix_stocks_part_id", "stocks", ["part_id"])
    op.create_index("ix_stocks_dealer_id", "stocks", ["dealer_id"])


def downgrade() -> None:
    op.drop_table("stocks")
    op.drop_table("dealers")
