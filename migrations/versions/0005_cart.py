"""cart items

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "stock_id", name="uq_cart_user_stock"),
        sa.CheckConstraint("quantity > 0", name="ck_cart_quantity"),
    )
    op.create_index("ix_cart_items_user_id", "cart_items", ["user_id"])


def downgrade() -> None:
    op.drop_table("cart_items")
