"""regions table + users.region_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27

Список регионов хранится в PostgreSQL. Здесь он только заполняется один раз.
Позже регионы можно добавлять/отключать прямо в базе (поле active) — код менять не нужно.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

REGIONS = [
    # code, name_ru, name_en, name_uz
    ("tashkent_city", "Ташкент", "Tashkent", "Toshkent shahri"),
    ("tashkent", "Ташкентская область", "Tashkent Region", "Toshkent viloyati"),
    ("samarkand", "Самаркандская область", "Samarkand Region", "Samarqand viloyati"),
    ("bukhara", "Бухарская область", "Bukhara Region", "Buxoro viloyati"),
    ("andijan", "Андижанская область", "Andijan Region", "Andijon viloyati"),
    ("fergana", "Ферганская область", "Fergana Region", "Farg‘ona viloyati"),
    ("namangan", "Наманганская область", "Namangan Region", "Namangan viloyati"),
    ("kashkadarya", "Кашкадарьинская область", "Kashkadarya Region", "Qashqadaryo viloyati"),
    ("surkhandarya", "Сурхандарьинская область", "Surkhandarya Region", "Surxondaryo viloyati"),
    ("khorezm", "Хорезмская область", "Khorezm Region", "Xorazm viloyati"),
    ("karakalpakstan", "Каракалпакстан", "Karakalpakstan", "Qoraqalpog‘iston"),
    ("jizzakh", "Джизакская область", "Jizzakh Region", "Jizzax viloyati"),
    ("navoi", "Навоийская область", "Navoi Region", "Navoiy viloyati"),
    ("syrdarya", "Сырдарьинская область", "Syrdarya Region", "Sirdaryo viloyati"),
]


def upgrade() -> None:
    regions = op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name_ru", sa.String(128), nullable=False),
        sa.Column("name_en", sa.String(128)),
        sa.Column("name_uz", sa.String(128)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.bulk_insert(
        regions,
        [
            {"code": c, "name_ru": ru, "name_en": en, "name_uz": uz, "sort_order": i * 10, "active": True}
            for i, (c, ru, en, uz) in enumerate(REGIONS, start=1)
        ],
    )
    op.add_column("users", sa.Column("region_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_region_id", "users", "regions", ["region_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_region_id", "users", type_="foreignkey")
    op.drop_column("users", "region_id")
    op.drop_table("regions")
