"""Синхронизация с CarSale: запись в базу, проверки безопасности, журнал (без настоящего браузера)."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, BotSetting, Dealer, Part, Region, Stock, SyncRun
from app.sync.carsale import CarsaleError, DealerResult, Snapshot
from app.sync.runner import REQUEST_KEY, SyncConfig, loop, run_sync, take_request

CFG = SyncConfig(login="partsbot", password="x", every_minutes=30)


def row(qty, code, name, dealer, status="У дилера", typ="A", model="—", price="1200"):
    return ["1", str(qty), code, name, status, typ, model, "1000", price, "—", "—", "—", dealer,
            f"JAC Motors Toshkent Store / {dealer}", "30.09.2026 09:12:06"]


def snapshot(rows):
    snap = Snapshot(rows=rows)
    for dealer in dict.fromkeys(r[12] for r in rows):
        mine = [r for r in rows if r[12] == dealer]
        snap.dealers.append(DealerResult(dealer, len(mine), sum(int(r[1]) for r in mine), None))
    return snap


def fetcher_for(snap=None, error=None):
    async def fetch(cfg):
        if error:
            raise error
        return snap
    return fetch


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = create_session_factory(engine)
    async with f() as s:
        s.add(Region(id=1, code="tashkent_city", name_ru="Ташкент"))
        await s.commit()
    yield f
    await engine.dispose()


async def count(f, model):
    async with f() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def test_sync_writes_stock_and_log(factory):
    snap = snapshot([row(4, "1601100V0011", "CLUTCH PRESSURE PLATE", "OOO «China Group»", typ="C"),
                     row(50, "1010208GD190", "FILTER", "OOO «SINO RONGLONG GROUP»"),
                     row(2, "1010208GD190", "FILTER", "OOO «China Group»")])
    run = await run_sync(factory, CFG, "manual", fetcher_for(snap))
    assert run.status == "ok" and run.error == "" and (run.rows, run.dealers, run.pieces) == (3, 2, 56)
    assert "Каталог обновлён" in run.summary
    async with factory() as s:
        stocks = {(st.part.part_number, st.dealer.name): st.quantity for st in (await s.scalars(select(Stock))).unique()}
        assert stocks[("1010208GD190", "OOO «SINO RONGLONG GROUP»")] == 50
        assert (await s.scalar(select(Stock).where(Stock.quantity == 4))).price == Decimal("1200")
    assert await count(factory, Dealer) == 2


async def test_failed_fetch_changes_nothing(factory):
    await run_sync(factory, CFG, fetcher=fetcher_for(snapshot([row(5, "A1", "ECU", "OOO «China Group»")])))
    run = await run_sync(factory, CFG, fetcher=fetcher_for(error=CarsaleError("CarSale не пустил")))
    assert run.status == "failed" and "не пустил" in run.error
    async with factory() as s:
        assert (await s.scalar(select(Stock))).quantity == 5


async def test_too_many_hidden_is_refused(factory):
    many = [row(1, f"P{i:03d}", f"PART {i}", "OOO «China Group»") for i in range(40)]
    assert (await run_sync(factory, CFG, fetcher=fetcher_for(snapshot(many)))).status == "ok"
    run = await run_sync(factory, CFG, fetcher=fetcher_for(snapshot(many[:5])))  # пропало 35 из 40
    assert run.status == "failed" and "слишком много" in run.error
    async with factory() as s:
        assert await s.scalar(select(func.count(Part.id)).where(Part.active.is_(True))) == 40


async def test_manual_request_flag_and_loop(factory):
    async with factory() as s:
        s.add(BotSetting(key=REQUEST_KEY, value="2026-09-30T10:00:00"))
        await s.commit()
    assert await take_request(factory) is True and await take_request(factory) is False
    snap = snapshot([row(3, "B1", "BELT", "ИП OOO «LUCKYCAR»")])
    await loop(factory, CFG, bot=None, settings=None, fetcher=fetcher_for(snap), once=True)
    async with factory() as s:
        runs = list(await s.scalars(select(SyncRun)))
    assert [r.status for r in runs] == ["ok"]


async def test_loop_without_credentials_does_nothing(factory):
    await loop(factory, SyncConfig(), bot=None, settings=None, fetcher=fetcher_for(error=AssertionError), once=True)
    assert await count(factory, SyncRun) == 0


def test_write_xlsx_is_valid_warehouse_export(tmp_path):
    from app.services.excel_import import validate_any
    from app.sync.carsale import write_xlsx

    path = write_xlsx(snapshot([row(7, "X1", "OIL FILTER", "OOO «ASIAMOTOR»", model="T8-P30BF")]), tmp_path / "s.xlsx")
    rows, errors, _, fmt = validate_any(path, [Region(id=1, code="tashkent_city", name_ru="Ташкент")])
    assert fmt == "warehouse" and errors == [] and rows[0].stock == 7 and rows[0].model["ru"] == "JAC T8"
