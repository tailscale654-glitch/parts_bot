"""Чат с клиентами в веб-панели: диалоги и сообщения

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(8), nullable=False, server_default="open", index=True),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("web_users.id", ondelete="SET NULL")),
        sa.Column("unread", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("support_chats.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("file_id", sa.String(255)),
        sa.Column("file_kind", sa.String(16)),
        sa.Column("file_name", sa.String(255)),
        sa.Column("web_user_id", sa.Integer(), sa.ForeignKey("web_users.id", ondelete="SET NULL")),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("support_messages")
    op.drop_table("support_chats")
