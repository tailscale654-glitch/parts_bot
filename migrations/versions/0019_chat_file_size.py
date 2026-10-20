"""Чат: размер файла и превью (кадр видео) — чтобы показать, почему большой файл не открывается

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_messages", sa.Column("file_size", sa.Integer()))
    op.add_column("support_messages", sa.Column("thumb_id", sa.String(255)))


def downgrade() -> None:
    op.drop_column("support_messages", "thumb_id")
    op.drop_column("support_messages", "file_size")
