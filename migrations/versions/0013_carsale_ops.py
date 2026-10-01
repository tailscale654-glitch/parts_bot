"""carsale_ops: заказы бота, записанные (или поставленные в очередь) в CarSale

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carsale_ops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="sale"),
        # queued → running → done | dry | failed | unknown (оборвалось после «Сохранить» — проверить вручную)
        sa.Column("status", sa.String(16), nullable=False, server_default="queued", index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "kind", name="uq_carsale_ops_order_kind"),
    )


def downgrade() -> None:
    op.drop_table("carsale_ops")
