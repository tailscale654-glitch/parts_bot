"""Чат: когда клиент последний раз был активен в боте — для отметки «прочитано» (✓✓)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_chats", sa.Column("client_seen_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("support_chats", "client_seen_at")
