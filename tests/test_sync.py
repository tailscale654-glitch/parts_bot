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


# ---------- продажи бота → CarSale ----------

from app.database.models import CarModel, CarsaleOp, Node, Order, OrderItem, User  # noqa: E402
from app.database.repositories.orders import OrderRepository  # noqa: E402
from app.sync.carsale_orders import AfterSaveError, SaleResult, phone_digits, pick_stock  # noqa: E402
from app.sync.runner import mark_stale, process_sales, sale_request  # noqa: E402


async def ready_order(f, status="READY"):
    async with f() as s:
        stock = await s.scalar(select(Stock))
        if stock is None:
            dealer = Dealer(region_id=1, name="OOO «China Group»")
            part = Part(name_ru="Фильтр", name_en="FILTER", part_number="1010208GD190",
                        model=CarModel(name_ru="Прочее"), node=Node(name_ru="ТО"))
            stock = Stock(part=part, dealer=dealer, price=Decimal(85500), quantity=10)
            s.add(stock)
            await s.flush()
        n = await s.scalar(select(func.count(User.id)))
        user = User(telegram_id=77 + n, first_name="Азиз", phone="998901234567", language="ru", region_id=1)
        order = Order(user=user, dealer_id=stock.dealer_id, status=status, total_amount=Decimal(171000))
        order.items = [OrderItem(part_id=stock.part_id, stock_id=stock.id, part_number="1010208GD190",
                                 name_ru="Фильтр", name_en="FILTER", quantity=2, price=Decimal(85500),
                                 total=Decimal(171000))]
        s.add(order)
        await s.commit()
        return order.id


async def complete(f, order_id):
    async with f() as s:
        order = await s.get(Order, order_id)
        assert await OrderRepository(s).set_status(order, "COMPLETED")
        await s.commit()


async def ops(f):
    async with f() as s:
        return list((await s.scalars(select(CarsaleOp).order_by(CarsaleOp.id))).unique())


def test_helpers():
    assert phone_digits("+998 90 123-45-67") == "901234567"
    assert pick_stock([(0, 1), (1, 10), (2, 5)], 4) == 1 and pick_stock([(0, 1)], 2) is None


async def test_completed_order_is_queued_only_when_enabled(factory, monkeypatch):
    monkeypatch.setenv("CARSALE_ORDERS", "off")
    await complete(factory, await ready_order(factory))
    assert await ops(factory) == []
    monkeypatch.setenv("CARSALE_ORDERS", "dry")
    order_id = await ready_order(factory)
    await complete(factory, order_id)
    queued = await ops(factory)
    assert [(o.order_id, o.status) for o in queued] == [(order_id, "queued")]
    async with factory() as s:
        req = sale_request(await s.get(Order, order_id))
    assert (req.client_phone, req.dealer_key, req.lines[0].quantity) == ("+998901234567", "chinagroup", 2)
    assert "заказ №" in req.note


async def test_process_sales_outcomes(factory, monkeypatch):
    monkeypatch.setenv("CARSALE_ORDERS", "on")
    ids = [await ready_order(factory) for _ in range(3)]
    for i in ids:
        await complete(factory, i)
    outcomes = iter([SaleResult(saved=True, message="ok"), CarsaleError("нет запчасти"), AfterSaveError("не закрылась")])
    seen_save = []

    async def submitter(req, cfg, save):
        seen_save.append(save)
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    assert await process_sales(factory, CFG, None, None, submitter) == 3
    assert [o.status for o in await ops(factory)] == ["done", "failed", "unknown"]
    assert seen_save == [True, True, True]
    assert await process_sales(factory, CFG, None, None, submitter) == 0  # ничего не повторяет само


async def test_queued_sale_keeps_stock_reserved_and_stale_running_becomes_unknown(factory, monkeypatch):
    monkeypatch.setenv("CARSALE_ORDERS", "on")
    order_id = await ready_order(factory)
    await complete(factory, order_id)
    # синхронизация пришла раньше, чем бот списал в CarSale: 10 шт. в CarSale, 2 из них уже выданы
    snap = snapshot([row(10, "1010208GD190", "FILTER", "OOO «China Group»")])
    run = await run_sync(factory, CFG, fetcher=fetcher_for(snap))
    assert run.status == "ok" and "Вычтено из остатков" in run.summary
    async with factory() as s:
        assert (await s.scalar(select(Stock))).quantity == 8
        op = (await s.scalars(select(CarsaleOp))).unique().one()
        op.status = "running"
        await s.commit()
    await mark_stale(factory)
    assert (await ops(factory))[0].status == "unknown"


async def test_untranslated_names_are_reported_once(factory):
    from types import SimpleNamespace

    from app.sync.runner import notify

    sent = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            sent.append(text)

    settings = SimpleNamespace(admin_ids=[1], web_url="https://panel")
    snap = snapshot([row(1, "Z1", "FLUX CAPACITOR UNKNOWN", "OOO «China Group»"),
                     row(1, "Z2", "OIL FILTER", "OOO «China Group»")])
    for _ in range(2):
        run = await run_sync(factory, CFG, fetcher=fetcher_for(snap))
        await notify(FakeBot(), factory, settings, run)
    hits = [t for t in sent if "без перевода" in t]
    assert len(hits) == 1 and "FLUX CAPACITOR UNKNOWN" in hits[0] and "OIL FILTER" not in hits[0]
    assert "https://panel/catalog?show=untranslated" in hits[0]
