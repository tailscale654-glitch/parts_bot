"""Справочник запчастей завода: формат файла, объединение моделей, модель для деталей без модели."""
import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, BotSetting, CarModel, Part, PartCatalog, Region
from app.services import import_flow
from app.services.excel_import import validate_any
from app.services.part_catalog import SYNC_REQUEST_KEY, model_codes
from app.sync.carsale import write_xlsx
from app.sync.runner import SyncConfig, run_sync
from tests.test_sync import fetcher_for, row, snapshot

REGIONS = [Region(id=1, code="tashkent_city", name_ru="Ташкент")]


def catalog_file(path, header, rows, title_rows=0):
    book = openpyxl.Workbook()
    sheet = book.active
    for _ in range(title_rows):
        sheet.append(["Список запчастей"])
    sheet.append(header)
    for r in rows:
        sheet.append(r)
    book.create_sheet("Sheet2")  # пустые листы не мешают
    book.save(path)
    return path


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = create_session_factory(engine)
    async with f() as s:
        s.add(Region(id=1, code="tashkent_city", name_ru="Ташкент"))
        await s.commit()
    yield f
    await engine.dispose()


def test_model_codes():
    assert model_codes("RF8-V9AA3,V9HA0") == ["RF8-V9AA3", "RF8-V9HA0"]
    assert model_codes("T9-P33Z3,T8-P30BF") == ["T9-P33Z3", "T8-P30BF"]
    assert model_codes("SUNRAY") == ["Sunray"] and model_codes(None) == []


def test_three_layouts_are_recognized(tmp_path):
    a = catalog_file(tmp_path / "a.xlsx", ["MODEL", "SN", "part code", "Spare part name (Detail name)"],
                     [["Sunray", 1, "D193-BJ", "BARE ENGINE Sunray"], ["M4", 2, "D193-BJ", "BARE ENGINE M4"]])
    b = catalog_file(tmp_path / "b.xlsx", ["SN", "MODEL", "part code", "EN NAME"],
                     [[1, "JS8P", "3503300S5500", "FRONT BRAKE DISC"], [2, "JS8P", None, None]])
    c = catalog_file(tmp_path / "c.xlsx", ["MODEL", "SN", "PARTS CODE", "DESCRIPTION(EN)"],
                     [["T8-P30BF", 1, "8210100P3113-HCJ", "MIRROR ASSY.（SILVER）"]], title_rows=2)
    rows, errors, _, fmt = validate_any(a, REGIONS)
    assert fmt == "catalog" and errors == [] and len(rows) == 1
    assert rows[0].models == ["Sunray", "M4"] and rows[0].name_en == "BARE ENGINE"
    rows, _, _, fmt = validate_any(b, REGIONS)
    assert fmt == "catalog" and [r.part_number for r in rows] == ["3503300S5500"]
    rows, _, _, fmt = validate_any(c, REGIONS)
    assert fmt == "catalog" and rows[0].name_en == "MIRROR ASSY.(SILVER)"


async def test_catalog_gives_models_to_parts_without_model(factory, tmp_path):
    # 1. В боте деталь без модели («—» в CarSale) → «Все модели»
    snap = snapshot([row(5, "1010208GD190", "FILTER", "OOO «China Group»"),
                     row(2, "B1", "BELT", "OOO «China Group»", model="T8-P30BF")])
    assert (await run_sync(factory, SyncConfig(login="x", password="x"), fetcher=fetcher_for(snap))).status == "ok"

    # 2. Загружаем справочник: два файла, модели одного артикула объединяются
    first = catalog_file(tmp_path / "1.xlsx", ["MODEL", "SN", "part code", "Spare part name"],
                         [["M4", 1, "1010208GD190", "OIL FILTER M4"]])
    second = catalog_file(tmp_path / "2.xlsx", ["SN", "MODEL", "part code", "EN NAME"],
                          [[1, "M3", "1010208gd190 ", "OIL FILTER"]])
    for path in (first, second):
        async with factory() as s:
            rows, errors, _, fmt = await import_flow.validate_path(s, path)
            assert fmt == "catalog" and not errors
            preview = await import_flow.dry_run(factory, rows, fmt)
            assert preview.in_bot == 1
            stats = await import_flow.run_import(s, rows, fmt)
            await s.commit()
    assert "в боте" in import_flow.stats_text("applied", stats, "catalog", "ru")
    async with factory() as s:
        item = await s.scalar(select(PartCatalog))
        assert (item.models, item.key) == ("M4,M3", "1010208GD190")
        assert (await s.get(BotSetting, SYNC_REQUEST_KEY)).value  # сервис sync запустит обновление сразу

    # 3. Следующая синхронизация: деталь в своих моделях; «скрыто» — 0, ведь из прайса ничего не пропало
    run = await run_sync(factory, SyncConfig(login="x", password="x"), fetcher=fetcher_for(snap))
    assert run.status == "ok" and "Скрыто: 0" in run.summary
    async with factory() as s:
        active = (await s.execute(select(CarModel.name_ru).join(Part, Part.model_id == CarModel.id)
                                  .where(Part.active.is_(True), Part.part_number == "1010208GD190"))).scalars()
        assert sorted(active) == ["JAC M3", "JAC M4 Luxe"]


def test_warehouse_without_catalog_keeps_all_models(tmp_path):
    path = write_xlsx(snapshot([row(1, "X1", "OIL FILTER", "OOO «ASIAMOTOR»")]), tmp_path / "w.xlsx")
    rows, _, _, _ = validate_any(path, REGIONS)
    assert rows[0].model["ru"] == "Все модели"
    rows, _, warnings, _ = validate_any(path, REGIONS, catalog={"X1": "RF8-V9AA3,RF8-V9HA0"})
    assert [r.model["ru"] for r in rows] == ["JAC RF8"] and any(w.key == "warn_model_from_catalog" for w in warnings)
