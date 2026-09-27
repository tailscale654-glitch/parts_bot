"""orders and order items

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dealer_id", sa.Integer(), sa.ForeignKey("dealers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="NEW"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('NEW', 'CONFIRMED', 'READY', 'COMPLETED', 'CANCELLED')", name="ck_orders_status"
        ),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_dealer_id", "orders", ["dealer_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id", ondelete="SET NULL")),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id", ondelete="SET NULL")),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column("name_ru", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("name_uz", sa.String(255)),
        sa.Column("model_name", sa.String(128)),
        sa.Column("node_name", sa.String(128)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    # Номера заказов начинаются с 10001 — выглядят солиднее, чем «Заказ №1»
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER SEQUENCE orders_id_seq RESTART WITH 10001")


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
