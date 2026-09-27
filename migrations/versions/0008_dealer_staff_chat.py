"""dealer staff, invites, order messages

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dealer_staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dealer_id", sa.Integer(), sa.ForeignKey("dealers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dealer_staff_dealer_id", "dealer_staff", ["dealer_id"])
    op.create_table(
        "dealer_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(32), nullable=False, unique=True),
        sa.Column("dealer_id", sa.Integer(), sa.ForeignKey("dealers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_table(
        "order_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("to_side", sa.String(8), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("to_side IN ('client', 'dealer')", name="ck_order_messages_side"),
    )
    op.create_index("ix_order_messages_order_id", "order_messages", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_messages")
    op.drop_table("dealer_invites")
    op.drop_table("dealer_staff")
