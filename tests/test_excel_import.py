from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, CarModel, Dealer, Part, Region, Stock
from app.scripts.seed_demo import seed
from app.services.excel_import import apply_import, validate_file
from app.services.excel_template import build_template

REGIONS = [
    Region(id=1, code="tashkent_city", name_ru="Ташкент", name_en="Tashkent", name_uz="Toshkent shahri"),
    Region(id=3, code="samarkand", name_ru="Самаркандская область", name_en="Samarkand Region", name_uz="Samarqand viloyati"),
]

BASE = {
    "region": "Ташкент", "dealer": "JAC Ташкент №1", "model_ru": "JAC JS4", "node_ru": "Двигатель",
    "node_en": "Engine", "part_name_ru": "Масляный фильтр", "part_name_en": "Oil filter",
    "part_number": "101001", "price": "85000", "stock": "12",
}


def make_xlsx(tmp_path: Path, rows: list[dict], sheet: str = "parts") -> Path:
    path = tmp_path / "file.xlsx"
    pd.DataFrame(rows).to_excel(path, sheet_name=sheet, index=False)
    return path


def keys(errors):
    return [(e.row, e.key) for e in errors]


# ---------- проверка файла ----------

def test_template_is_valid(tmp_path):
    path = tmp_path / "t.xlsx"
    path.write_bytes(build_template())
    rows, errors = validate_file(path, REGIONS)
    assert errors == [] and len(rows) == 3


def test_not_excel(tmp_path):
    path = tmp_path / "bad.xlsx"
    path.write_text("hello")
    assert keys(validate_file(path, REGIONS)[1]) == [(0, "err_unreadable")]


def test_missing_columns(tmp_path):
    path = make_xlsx(tmp_path, [{"region": "Ташкент", "dealer": "X"}])
    errors = validate_file(path, REGIONS)[1]
    assert errors[0].key == "err_missing_columns" and "price" in errors[0].params["columns"]


def test_row_errors_with_excel_row_numbers(tmp_path):
    rows = [
        BASE,
        {**BASE, "part_number": "2", "price": ""},                 # строка 3: нет цены
        {**BASE, "part_number": "3", "price": "abc"},              # строка 4: цена не число
        {**BASE, "part_number": "4", "stock": "1.5"},              # строка 5: дробный остаток
        {**BASE, "part_number": "5", "region": "Марс"},            # строка 6: нет такого региона
        {**BASE},                                                   # строка 7: дубль строки 2
        {**BASE, "dealer": "JAC Ташкент №2", "node_ru": "Кузов"},  # строка 8: другая категория у того же артикула
        {**BASE, "part_number": ""},                                # строка 9: нет артикула
    ]
    errors = validate_file(make_xlsx(tmp_path, rows), REGIONS)[1]
    assert keys(errors) == [
        (3, "err_empty"), (4, "err_price"), (5, "err_stock"), (6, "err_region"),
        (7, "err_duplicate"), (8, "err_conflict_node"), (9, "err_empty"),
    ]
    assert errors[4].params["other"] == 2


def test_values_are_normalized(tmp_path):
    rows = [
        {**BASE, "part_number": "00123", "price": "85 000,50", "region": "Samarqand viloyati"},
        {**BASE, "part_number": "777", "price": 90000, "stock": 3.0, "region": "tashkent_city"},
    ]
    parsed, errors = validate_file(make_xlsx(tmp_path, rows), REGIONS)
    assert errors == []
    assert parsed[0].part_number == "00123"  # ведущие нули не теряются
    assert parsed[0].price == Decimal("85000.50") and parsed[0].region_id == 3
    assert parsed[1].stock == 3 and parsed[1].part_number == "777" and parsed[1].region_id == 1


def test_empty_lines_ignored_and_first_sheet_used(tmp_path):
    path = make_xlsx(tmp_path, [BASE, {k: None for k in BASE}], sheet="Лист1")
    rows, errors = validate_file(path, REGIONS)
    assert errors == [] and len(rows) == 1


# ---------- запись в базу ----------

@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = create_session_factory(engine)
    async with f() as s:
        s.add_all([Region(id=r.id, code=r.code, name_ru=r.name_ru, name_en=r.name_en, name_uz=r.name_uz) for r in REGIONS])
        await s.commit()
    yield f
    await engine.dispose()


async def test_import_new_update_hide(tmp_path, factory):
    async with factory() as s:
        await seed(s)  # 80 демо-деталей
    file1 = [BASE, {**BASE, "dealer": "JAC Ташкент №2", "price": "82000", "stock": "0"},
             {**BASE, "part_number": "102001", "node_ru": "Тормозная система", "part_name_ru": "Колодки", "region": "Samarkand Region", "dealer": "JAC Самарканд"}]
    rows, errors = validate_file(make_xlsx(tmp_path, file1), REGIONS)
    assert errors == []
    async with factory() as s:
        stats = await apply_import(s, rows)
        await s.commit()
    assert (stats.new, stats.updated, stats.hidden) == (2, 0, 80)  # демо скрыто: его нет в файле
    assert (stats.parts, stats.dealers, stats.regions, stats.models) == (2, 3, 2, 1)

    async with factory() as s:
        part = await s.scalar(select(Part).where(Part.part_number == "101001"))
        assert part.name_en == "Oil filter" and part.node.name_en == "Engine" and part.active
        prices = sorted(st.price for st in await s.scalars(select(Stock).where(Stock.part_id == part.id)))
        assert prices == [Decimal("82000"), Decimal("85000")]

    # Второй файл: цена изменилась, дилер №2 и колодки убраны
    rows, _ = validate_file(make_xlsx(tmp_path, [{**BASE, "price": "90000", "part_name_en": ""}]), REGIONS)
    async with factory() as s:
        stats = await apply_import(s, rows)
        await s.commit()
    assert (stats.new, stats.updated, stats.hidden) == (0, 1, 1)
    async with factory() as s:
        part = await s.scalar(select(Part).where(Part.part_number == "101001"))
        assert part.name_en == "Oil filter"  # пустой перевод не стёр старый
        stocks = list(await s.scalars(select(Stock)))
        assert [(st.price, st.quantity) for st in stocks] == [(Decimal("90000.00"), 12)]
        dealer2 = await s.scalar(select(Dealer).where(Dealer.name == "JAC Ташкент №2"))
        assert dealer2.active is False


async def test_dry_run_rollback_changes_nothing(tmp_path, factory):
    rows, _ = validate_file(make_xlsx(tmp_path, [BASE]), REGIONS)
    async with factory() as s:
        stats = await apply_import(s, rows)
        await s.rollback()
    assert stats.new == 1
    async with factory() as s:
        assert list(await s.scalars(select(CarModel))) == []
        assert list(await s.scalars(select(Part))) == []
