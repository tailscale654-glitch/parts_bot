"""Предзаказ со склада JAC: CarSale «На складе» → деталь видна в каталоге с пометкой «под заказ»,
клиент выбирает дилера своего региона, заказ идёт отдельным «предзаказом»."""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, Dealer, Order, Part, Region, Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.catalog import CatalogRepository
from app.database.repositories.orders import OrderRepository
from app.database.repositories.stocks import StockRepository
from app.handlers.catalog import card_view
from app.services.catalog import days_text
from app.services.orders import checkout_preview_text, order_line, order_text, progress_lines
from app.sync.carsale import Snapshot
from app.sync.runner import SyncConfig, run_sync
from tests.test_sync import fetcher_for, row, snapshot

CFG = SyncConfig(login="partsbot", password="x")
STORE = "JAC Motors Toshkent Store"


def wh(qty, code, name, model="M4", price="1431911", assigned="—"):
    """Строка склада JAC: статус «На складе», название склада — в колонке «Склад»."""
    return ["1", str(qty), code, name, "На складе", "D", model, "1193310", price, STORE, "A-1", "INV",
            assigned, "", "30.09.2026 09:12:06"]


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pre.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = create_session_factory(engine)
    async with f() as s:
        tash = Region(id=1, code="tashkent_city", name_ru="Ташкент", preorder_days="1-2")
        sam = Region(id=2, code="samarkand", name_ru="Самарканд", preorder_days="3")
        s.add_all([tash, sam, Region(id=3, code="khorezm", name_ru="Хорезм")])
        # дилеры из справочника: их регион не меняется импортом
        s.add_all([Dealer(id=1, region_id=1, name="OOO «China Group»", in_directory=True),
                   Dealer(id=2, region_id=1, name="OOO «ASIAMOTOR»", in_directory=True),
                   Dealer(id=3, region_id=2, name="JAC Samarqand", in_directory=True, active=False)])
        s.add_all([User(id=1, telegram_id=11, language="ru", region_id=1, phone="+998901112233", car_model="JAC M4 Luxe"),
                   User(id=2, telegram_id=12, language="ru", region_id=2, phone="+998901112234", car_model="JAC M4 Luxe"),
                   User(id=3, telegram_id=13, language="ru", region_id=3, phone="+998901112235", car_model="JAC M4 Luxe")])
        await s.commit()
    yield f
    await engine.dispose()


async def sync(factory, dealer_rows, warehouse_rows=(), warehouse_error="", cfg=CFG):
    snap = snapshot(list(dealer_rows))
    snap.warehouse_rows, snap.warehouse_error = list(warehouse_rows), warehouse_error
    run = await run_sync(factory, cfg, "manual", fetcher_for(snap))
    assert run.status == "ok", run.error
    return run


async def stock_of(s, number, dealer_name):
    return (await s.scalars(select(Stock).join(Part).join(Dealer, Dealer.id == Stock.dealer_id)
                            .where(Part.part_number == number, Dealer.name == dealer_name))).unique().one_or_none()


def test_days_text():
    assert days_text("1-2", "ru") == "1–2 дня" and days_text("3-5", "ru") == "3–5 дней"
    assert days_text("1", "ru") == "1 день" and days_text("21", "ru") == "21 день" and days_text("11", "ru") == "11 дней"
    assert days_text("2", "en") == "2 days" and days_text("1", "en") == "1 day" and days_text("1-2", "uz") == "1–2 kun"
    assert days_text(None, "ru") == "3–5 дней"  # срок не задан


async def test_warehouse_rows_become_preorder_stock(factory):
    run = await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")],
                     [wh(15, "B1", "BSM"), wh(3, "A1", "ECU"), wh(1, "C1", "LAMP", assigned="OOO «ASIAMOTOR»")])
    assert "На складе JAC (предзаказ): 2 дет." in run.summary and "закреплены за дилером: 1" in run.summary
    async with factory() as s:
        store = await s.scalar(select(Dealer).where(Dealer.name == STORE))
        assert store.is_warehouse and store.active
        assert (await stock_of(s, "B1", STORE)).quantity == 15
        assert await stock_of(s, "C1", STORE) is None  # уже едет к дилеру — не для предзаказа
        # склад — не дилер: в предложениях региона его нет, в «Все дилеры» тоже
        b1 = await s.scalar(select(Part).where(Part.part_number == "B1"))
        assert await StockRepository(s).offers_in_region(b1.id, 1) == []
        assert (await StockRepository(s).warehouse_offer(b1.id)).dealer.name == STORE


async def test_catalog_shows_warehouse_parts_where_there_is_a_dealer(factory):
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")], [wh(15, "B1", "BSM")])
    async with factory() as s:
        b1 = await s.scalar(select(Part).where(Part.part_number == "B1"))
        for region_id, visible in ((1, True), (2, True), (3, False)):  # Хорезм — нет дилеров, некуда привезти
            parts = await CatalogRepository(s, region_id).list_parts(b1.model_id, b1.node_id, "ru", 0, 10)
            assert (b1.id in [p.id for p in parts]) is visible, region_id
        store = await s.scalar(select(Dealer).where(Dealer.name == STORE))
        store.enabled = False  # склад выключили в панели → предзаказ выключен
        await s.commit()
        assert await CatalogRepository(s, 1).list_parts(b1.model_id, b1.node_id, "ru", 0, 10) == []


async def test_card_cart_and_order(factory):
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")], [wh(5, "B1", "BSM")])
    async with factory() as s:
        user = await s.get(User, 1)
        b1 = await s.scalar(select(Part).where(Part.part_number == "B1"))
        text, kb, _ = await card_view(b1, user, s, page=1)
        assert "🚚 ПОД ЗАКАЗ" in text and "1 431 911 сум" in text and "Привезём к дилеру за 1–2 дня" in text
        assert "выберете на следующем шаге (в вашем регионе: 2)" in text  # два дилера в Ташкенте
        assert kb.inline_keyboard[0][0].text == "🚚 Заказать · 1 431 911 сум"
        assert kb.inline_keyboard[0][0].callback_data.startswith("pre:pick:")

        sam_user = await s.get(User, 2)
        text, kb, _ = await card_view(b1, sam_user, s, page=1)  # в Самарканде один дилер — сразу «Заказать»
        assert "Заберёте у дилера:" in text and "JAC Samarqand" in text and "3 дня" in text
        assert kb.inline_keyboard[0][0].callback_data.startswith("pre:add:")

        cart = CartRepository(s)
        stock = await StockRepository(s).warehouse_offer(b1.id)
        china, asia, samarqand = [await s.get(Dealer, i) for i in (1, 2, 3)]
        assert await cart.add(user, stock) == (False, 0)  # без дилера выдачи нельзя
        assert await cart.add(user, stock, pickup=samarqand) == (False, 0)  # дилер чужого региона
        assert await cart.add(user, stock, pickup=china) == (True, 1)
        assert await cart.add(user, stock, pickup=asia) == (True, 2)  # передумал — заберёт у ASIAMOTOR
        a1 = await stock_of(s, "A1", "OOO «China Group»")
        assert await cart.add(user, a1) == (True, 1)  # обычная покупка у дилера
        items = await cart.items(user)
        assert [i.dealer.name for i in items] == ["OOO «ASIAMOTOR»", "OOO «China Group»"]
        preview = checkout_preview_text(items, "ru")
        assert "🚚 Предзаказ со склада JAC · привезём за 1–2 дня" in preview and "2 отдельных заказа" in preview

        orders = await OrderRepository(s).create_from_cart(user)
        await s.commit()
        pre = next(o for o in orders if o.preorder)
        await s.refresh(pre)
        assert pre.dealer.name == "OOO «ASIAMOTOR»" and pre.source_dealer.name == STORE
        assert (await s.get(Stock, stock.id)).quantity == 3  # резерв — со склада
        client = order_text(pre, "ru")
        assert "Везём со склада JAC к дилеру — обычно 1–2 дня" in client and "✅ Оформлен\n⏳ Едет к дилеру" in client
        admin = order_text(pre, "ru", for_admin=True)
        assert f"ПРЕДЗАКАЗ: отправить со склада «{STORE}» → дилеру OOO «ASIAMOTOR»." in admin
        assert order_line(pre, "ru").startswith("🚚 №")

        await OrderRepository(s).set_status(pre, "CONFIRMED")
        assert "Подтверждён — везём к дилеру" in order_text(pre, "ru")
        await OrderRepository(s).set_status(pre, "CANCELLED")
        await s.commit()
        assert (await s.get(Stock, stock.id)).quantity == 5  # отмена — вернули на склад
        assert progress_lines(pre, "ru") == []


async def test_reimport_keeps_preorder_reserved_on_warehouse(factory):
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")], [wh(5, "B1", "BSM")])
    async with factory() as s:
        user = await s.get(User, 1)
        stock = await StockRepository(s).warehouse_offer((await s.scalar(select(Part).where(Part.part_number == "B1"))).id)
        await CartRepository(s).add(user, stock, pickup=await s.get(Dealer, 1))
        await CartRepository(s).add(user, stock, pickup=await s.get(Dealer, 1))
        [order] = await OrderRepository(s).create_from_cart(user)
        await s.commit()
        order_id = order.id
    # CarSale ещё не знает о заказе: на складе по-прежнему 5 → в боте 5 − 2 = 3
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")], [wh(5, "B1", "BSM")])
    async with factory() as s:
        assert (await stock_of(s, "B1", STORE)).quantity == 3
        order = await s.get(Order, order_id)
        order.status = "READY"  # доехала: в CarSale теперь «У дилера» у China Group
        await s.commit()
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4"),
                         row(2, "B1", "BSM", "OOO «China Group»", model="M4")], [wh(3, "B1", "BSM")])
    async with factory() as s:
        assert (await stock_of(s, "B1", STORE)).quantity == 3  # со склада больше не вычитаем
        assert (await stock_of(s, "B1", "OOO «China Group»")).quantity == 0  # обе штуки ждут клиента


async def test_warehouse_kept_when_not_read(factory):
    await sync(factory, [row(2, "A1", "ECU", "OOO «China Group»", model="M4")], [wh(5, "B1", "BSM")])
    # склад не прочитался — дилеры обновились, склад остался прежним
    run = await sync(factory, [row(4, "A1", "ECU", "OOO «China Group»", model="M4")], [], warehouse_error="Таблица склада не загрузилась")
    assert "Склад JAC не прочитан (Таблица склада не загрузилась)" in run.summary
    assert "На складе JAC (предзаказ): 1 дет." in run.summary
    async with factory() as s:
        assert (await stock_of(s, "B1", STORE)).quantity == 5
        assert (await stock_of(s, "A1", "OOO «China Group»")).quantity == 4
        assert (await s.scalar(select(Part).where(Part.part_number == "B1"))).active
    # предзаказ выключили (CARSALE_PREORDER=0) — склад очищается
    await sync(factory, [row(4, "A1", "ECU", "OOO «China Group»", model="M4")], cfg=SyncConfig(login="p", password="x", preorder=False))
    async with factory() as s:
        assert await stock_of(s, "B1", STORE) is None
        assert not (await s.scalar(select(Dealer).where(Dealer.name == STORE))).active


def test_snapshot_writes_warehouse_rows(tmp_path):
    from app.services.excel_import import validate_any
    from app.sync.carsale import write_xlsx

    snap = Snapshot(rows=[row(1, "A1", "ECU", "OOO «China Group»")], warehouse_rows=[wh(4, "B1", "BSM")])
    assert snap.warehouse_pieces == 4
    rows, errors, warnings, fmt = validate_any(write_xlsx(snap, tmp_path / "s.xlsx"),
                                               [Region(id=1, code="tashkent_city", name_ru="Ташкент")])
    assert errors == [] and {(r.part_number, r.warehouse, r.dealer) for r in rows} == {
        ("A1", False, "OOO «China Group»"), ("B1", True, STORE)}


# ---------- 🔎 поиск ----------

async def test_search_by_name_and_number(factory):
    from app.handlers.search import search_view
    from app.services.search import matches

    await sync(factory, [row(2, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «China Group»", model="M4"),
                         row(1, "5206100P3010", "FRONT WINDSHIELD", "OOO «China Group»", model="T8-P30BF"),
                         row(1, "X9", "SPARK PLUG", "OOO «China Group»")],
               [wh(5, "3608100V670001", "BSM")])
    async with factory() as s:
        user = await s.get(User, 1)  # JAC M4 Luxe, Ташкент
        text, kb = await search_view(user, s, "МАСЛЯНЫЙ фильтр", full=False)  # русский перевод, другой регистр
        assert "найдено: 1" in text and kb.inline_keyboard[0][0].text == "Масляный фильтр · 1017100GD050"
        assert kb.inline_keyboard[0][0].callback_data.endswith(":0")  # page=0 — «Назад» к результатам

        text, kb = await search_view(user, s, "1017100-gd", full=False)  # часть артикула с дефисом
        assert "найдено: 1" in text
        text, kb = await search_view(user, s, "3608100", full=False)  # только на складе — с пометкой 🚚
        assert kb.inline_keyboard[0][0].text.startswith("🚚 ") and "под заказ со склада JAC" in text
        text, kb = await search_view(user, s, "свеча", full=False)  # «Прочее» — подходит всем
        assert "найдено: 1" in text

        text, kb = await search_view(user, s, "windshield", full=False)  # деталь от T8 — клиенту M4 не показываем
        assert "ничего не нашлось" in text and kb.inline_keyboard[0][0].callback_data == "srch:manager:1"
        text, _ = await search_view(user, s, "windshield", full=True)  # сотрудник дилера — все модели
        assert "найдено: 1" in text

    class R:
        name_ru, name_en, name_uz, part_number = "Moy filtri", None, "Yog‘ filtri", "A-1"
    assert matches("yog'", R) and matches("ЙОГ", R) is False and matches("a1", R) is False  # «a1» — короче 3


async def test_search_mode_menu_and_manager(factory):
    """«🔎 Поиск» → текст ищется; другая кнопка меню — выход из поиска; «Спросить менеджера» → в чат панели."""
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from app.database.models import SupportMessage
    from app.handlers.search import ask_manager, do_search
    from app.handlers.start import leave_search
    from app.states.search import SearchStates

    await sync(factory, [row(2, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «China Group»", model="M4")])
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=11, user_id=11))
    await state.set_state(SearchStates.query)
    async with factory() as s:
        user = await s.get(User, 1)
        message = MagicMock(text="  тормозные   колодки ")
        message.answer = AsyncMock()
        await do_search(message, user, s, state)
        assert "ничего не нашлось" in message.answer.call_args.args[0]
        assert (await state.get_data())["search_q"] == "тормозные колодки"

        callback = MagicMock()
        callback.answer, callback.message.edit_text = AsyncMock(), AsyncMock()
        callback.message.photo = None
        bot, settings = MagicMock(), MagicMock(admin_ids=set(), web_url="")
        await ask_manager(callback, user, s, state, bot, settings)
        assert await state.get_state() is None  # дальше клиент пишет менеджеру как обычно
        note = await s.scalar(select(SupportMessage))
        assert note.text == "🔎 Клиент не нашёл в каталоге: «тормозные колодки»"
        assert "Отправили менеджеру" in callback.message.edit_text.call_args.args[0]

    await state.set_state(SearchStates.query)
    await leave_search(state)
    assert await state.get_state() is None and (await state.get_data())["search_q"]  # запрос помним
