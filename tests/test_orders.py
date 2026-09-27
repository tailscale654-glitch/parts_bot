from decimal import Decimal

import pytest

from app.database.models import Order, Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import CheckoutError, OrderRepository
from app.keyboards.orders import admin_order_keyboard, order_keyboard
from app.services.orders import checkout_preview_text, order_line, order_text
from tests.test_offers_cart import db  # noqa: F401 — та же тестовая база (3 дилера в Ташкенте + Самарканд)


async def fill_cart(db, user):
    cart = CartRepository(db)
    for stock_id, times in ((1, 2), (2, 3)):  # дилер №1: 2 шт. по 85 000; дилер №2: 3 шт. по 82 000
        for _ in range(times):
            await cart.add(user, await db.get(Stock, stock_id))


async def test_checkout_creates_order_per_dealer_and_reserves_stock(db):
    user = await db.get(User, 1)
    await fill_cart(db, user)
    preview = checkout_preview_text(await CartRepository(db).items(user), "ru")
    assert "будет создано 2 отдельных заказа" in preview and "💰 Итого: 416 000 сум" in preview

    orders = await OrderRepository(db).create_from_cart(user)
    await db.commit()
    assert len(orders) == 2
    totals = sorted(o.total_amount for o in orders)
    assert totals == [Decimal("170000"), Decimal("246000")]
    assert all(o.status == "NEW" for o in orders)
    assert (await db.get(Stock, 1)).quantity == 10 and (await db.get(Stock, 2)).quantity == 1  # резерв
    assert await CartRepository(db).items(user) == []  # корзина очищена

    item = orders[0].items[0]
    assert item.name_ru == "Масляный фильтр" and item.part_number == "101001" and item.model_name == "JAC JS4"


async def test_checkout_fails_when_stock_changed(db):
    user = await db.get(User, 1)
    await fill_cart(db, user)
    stock = await db.get(Stock, 2)
    stock.quantity = 1  # пока клиент думал, другой купил
    await db.commit()
    with pytest.raises(CheckoutError) as e:
        await OrderRepository(db).create_from_cart(user)
    await db.commit()  # как в обработчике: изменений нет, просто снимаем блокировку
    assert [(p.stock_id, p.wanted, p.available) for p in e.value.problems] == [(2, 3, 1)]
    from app.services.orders import stock_problems_text
    text = stock_problems_text(e.value.problems, "ru")
    assert "Масляный фильтр — сейчас в наличии 1 шт. (в корзине 3)" in text
    assert len(await CartRepository(db).items(user)) == 2  # корзина не тронута
    assert (await db.get(Stock, 1)).quantity == 12  # и остатки тоже


async def test_status_transitions_and_cancel_returns_stock(db):
    user = await db.get(User, 1)
    await fill_cart(db, user)
    repo = OrderRepository(db)
    order = next(o for o in await repo.create_from_cart(user) if o.dealer_id == 2)
    await db.commit()
    assert (await db.get(Stock, 2)).quantity == 1

    assert await repo.set_status(order, "COMPLETED") is False  # нельзя перескочить
    assert await repo.set_status(order, "CONFIRMED") is True
    assert await repo.set_status(order, "CONFIRMED") is False  # повторно — нет
    assert await repo.set_status(order, "CANCELLED") is True
    await db.commit()
    assert (await db.get(Stock, 2)).quantity == 4  # вернулось в остаток
    assert await repo.set_status(order, "READY") is False  # отменённый — конечный


async def test_order_texts_and_keyboards(db):
    user = await db.get(User, 1)
    user.phone = "+998901234567"
    await fill_cart(db, user)
    order = (await OrderRepository(db).create_from_cart(user))[0]
    await db.commit()
    await db.refresh(order)

    client = order_text(order, "ru")
    assert f"🧾 ЗАКАЗ №{order.id}" in client and "🟡 Новый" in client and "Телефон" not in client
    admin = order_text(order, "ru", for_admin=True)
    assert "🔔 НОВЫЙ ЗАКАЗ" in admin and "+998901234567" in admin and "🚗 JAC JS4 · 🔧 Двигатель" in admin
    assert "Ташкент" in admin
    assert order_line(order, "en").startswith(f"№{order.id} · ")

    assert [b.text for b in admin_order_keyboard(order, "ru").inline_keyboard[0]] == ["✅ Подтвердить", "❌ Отменить"]
    assert order_keyboard(order, "ru").inline_keyboard[0][0].text == "❌ Отменить заказ"
    order.status = "COMPLETED"
    assert admin_order_keyboard(order, "ru") is None
    assert len(order_keyboard(order, "ru").inline_keyboard) == 1  # только «К заказам»


async def test_user_sees_only_own_orders(db):
    user, other = await db.get(User, 1), await db.get(User, 2)
    await fill_cart(db, user)
    await OrderRepository(db).create_from_cart(user)
    await db.commit()
    repo = OrderRepository(db)
    assert len(await repo.for_user(user)) == 2 and await repo.for_user(other) == []
    assert isinstance((await repo.for_user(user))[0], Order)
