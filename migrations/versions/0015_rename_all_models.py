"""«Все модели» → «Прочее»: переименовать существующую модель, чтобы детали остались на месте

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # если «Прочее» как модель уже есть (не должно быть) — не трогаем, иначе нарушим уникальность названий
    op.execute("""
        UPDATE models SET name_ru = 'Прочее', name_en = 'Other', name_uz = 'Boshqa'
        WHERE name_ru = 'Все модели' AND NOT EXISTS (SELECT 1 FROM models WHERE name_ru = 'Прочее')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE models SET name_ru = 'Все модели', name_en = 'All models', name_uz = 'Barcha modellar'
        WHERE name_ru = 'Прочее'
    """)
