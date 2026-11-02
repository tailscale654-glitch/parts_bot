"""Предзаказ со склада JAC, срок предзаказа по регионам, точка дилера на карте, напоминание о заказе

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dealers", sa.Column("is_warehouse", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("dealers", sa.Column("latitude", sa.Float()))
    op.add_column("dealers", sa.Column("longitude", sa.Float()))
    op.add_column("regions", sa.Column("preorder_days", sa.String(16)))
    op.add_column("cart_items", sa.Column("pickup_dealer_id", sa.Integer(),
                                          sa.ForeignKey("dealers.id", ondelete="CASCADE")))
    op.add_column("orders", sa.Column("preorder", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("orders", sa.Column("source_dealer_id", sa.Integer(),
                                      sa.ForeignKey("dealers.id", ondelete="SET NULL")))
    op.add_column("orders", sa.Column("reminded_at", sa.DateTime(timezone=True)))
    # срок по умолчанию: Ташкент и область — 1–2 дня, остальные регионы — 3–5 (меняется в «⚙️ Настройки»)
    op.execute("UPDATE regions SET preorder_days = CASE WHEN code IN ('tashkent_city', 'tashkent') THEN '1-2' ELSE '3-5' END")


def downgrade() -> None:
    op.drop_column("orders", "reminded_at")
    op.drop_column("orders", "source_dealer_id")
    op.drop_column("orders", "preorder")
    op.drop_column("cart_items", "pickup_dealer_id")
    op.drop_column("regions", "preorder_days")
    op.drop_column("dealers", "longitude")
    op.drop_column("dealers", "latitude")
    op.drop_column("dealers", "is_warehouse")
