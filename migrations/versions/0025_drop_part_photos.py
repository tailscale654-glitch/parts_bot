"""Фото деталей из каталога JAC и jac-zap.ru убраны: удаляем их таблицы и ссылки на них у деталей

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-12
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ссылки «/media/parts/…» больше некому отдавать — у деталей остаются только фото, заданные в панели
    op.execute("UPDATE parts SET photo = NULL WHERE photo LIKE '/media/parts/%'")
    op.execute("DROP TABLE IF EXISTS epc_photos")
    op.execute("DROP TABLE IF EXISTS epc_images")


def downgrade() -> None:
    pass  # таблицы фото не восстанавливаем — функция удалена
