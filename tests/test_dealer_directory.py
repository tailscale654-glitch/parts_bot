import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, Dealer, Region
from app.database.repositories.stocks import StockRepository
from app.services.dealers import apply_directory, find_region, region_lookup
from app.services.excel_import import apply_import, validate_any
from app.utils.names import dealer_key
from tests.test_warehouse_import import make_export, row

REGIONS = [Region(id=i, code=c, name_ru=ru) for i, (c, ru) in enumerate([
    ("tashkent_city", "Ташкент"), ("tashkent", "Ташкентская область"), ("andijan", "Андижанская область"),
    ("karakalpakstan", "Каракалпакстан"), ("bukhara", "Бухарская область"),
], start=1)]


@pytest.mark.parametrize("a,b", [
    ("OOO «ASIAMOTOR»", '"Asia Motor" MChJ'),
    ("OOO «China Group»", "CHINA GROUP"),
    ("ИП «ООО JAC-AUTO»", "ИП ООО «JAC-AUTO»"),
    ("ООО «Navoiy Avtotrans xizmat»", '"Navoiy Avtotransxizmat" МЧЖ'),
    ("OOO «Avto-Grand Lyuks»", 'OOO "Avto Grand Lyuks"'),
    ('"RAYON AVTO" MCHJ', "Rayon Avto"),
])
def test_same_dealer_different_spelling(a, b):
    assert dealer_key(a) == dealer_key(b)


def test_different_dealers_differ():
    assert dealer_key("OOO «JAC MOTORS INDEX»") != dealer_key('OOO "INDEX AUTO MOTORS"')


def test_region_text_variants():
    lookup = region_lookup(REGIONS)
    assert find_region("город Ташкент", lookup) == 1
    assert find_region("Республика Каракалпакстан", lookup) == 4
    assert find_region("Андижанская область", lookup) == 3
    assert find_region("Марс", lookup) is None


def make_directory(tmp_path, rows):
    path = tmp_path / "dealers.xlsx"
    pd.DataFrame(rows, columns=["Название", "Код", "Адрес", "Район", "Номер телефона", "Оценка", "Статус"]).to_excel(path, index=False)
    return path


DIRECTORY = [
    ["CHINA GROUP", "CGP", "Андижон вилояти, ул. Мехнат, 10", "Андижанская область", "+998 94 417 00 32", "<span/>", "Активный"],
    ['"Asia Motor" MChJ', "ASM", "Сергелийский р-н", "город Ташкент", "+998 77 268 7118", "", "Активный"],
    ['ООО "AUTOCENTER NURAFSHON"', "ACN", "Nurafshon", "Ташкентская область", None, "", "Неактивный"],
]


async def test_directory_then_warehouse(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as s:
        s.add_all([Region(id=r.id, code=r.code, name_ru=r.name_ru) for r in REGIONS])
        await s.commit()

    rows, errors, _, fmt = validate_any(make_directory(tmp_path, DIRECTORY + [["X", "", "", "Марс", "", "", "Активный"]]), REGIONS)
    assert fmt == "directory" and [(e.row, e.key) for e in errors] == [(5, "err_region")]

    rows, errors, _, fmt = validate_any(make_directory(tmp_path, DIRECTORY), REGIONS)
    async with factory() as s:
        stats = await apply_directory(s, rows)
        await s.commit()
    assert (stats.new, stats.updated, stats.disabled) == (3, 0, 1)

    # Складская выгрузка: дилеры записаны иначе, регион берётся из справочника
    export = make_export(tmp_path, [
        row(2, "P1", "ECU", "У дилера", "D", "M3", 100, 200, "OOO «China Group»"),
        row(3, "P1", "ECU", "У дилера", "D", "M3", 100, 210, "OOO «ASIAMOTOR»"),
        row(4, "P1", "ECU", "У дилера", "D", "M3", 100, 190, "OOO «AUTOCENTER NURAFSHON»"),
    ])
    async with factory() as s:
        known = dict((await s.execute(select(Dealer.name_key, Dealer.region_id))).all())
    rows, errors, warnings, fmt = validate_any(export, REGIONS, known)
    assert fmt == "warehouse" and errors == [] and not [w for w in warnings if w.key == "warn_default_region"]
    async with factory() as s:
        await apply_import(s, rows)
        await s.commit()
        dealers = {d.name: d for d in await s.scalars(select(Dealer))}
        assert set(dealers) == {"CHINA GROUP", '"Asia Motor" MChJ', 'ООО "AUTOCENTER NURAFSHON"'}  # без дублей
        assert dealers["CHINA GROUP"].region_id == 3 and dealers["CHINA GROUP"].phone == "+998 94 417 00 32"

        repo = StockRepository(s)
        andijan = await repo.offers_in_region(1, 3)
        assert [o.dealer.name for o in andijan] == ["CHINA GROUP"]
        assert await repo.offers_in_region(1, 2) == []  # «Неактивный» в справочнике — скрыт
    await engine.dispose()
