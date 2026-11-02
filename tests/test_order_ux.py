"""Заказ глазами клиента: шкала, «Как добраться», «заказ готов» с меткой на карте, напоминание, «Повторить»."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.database.models import Dealer, Order, Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import OrderRepository
from app.keyboards.orders import order_keyboard
from app.services.catalog import map_url
from app.services.notify import notify_status_change, remind_ready
from app.services.orders import order_text
from tests.test_offers_cart import db  # noqa: F401 — 3 дилера в Ташкенте + Самарканд


async def new_order(db, qty=2):
    user = await db.get(User, 1)
    user.phone = "+998901112233"
    for _ in range(qty):
        await CartRepository(db).add(user, await db.get(Stock, 1))
    [order] = await OrderRepository(db).create_from_cart(user)
    await db.commit()
    await db.refresh(order)
    return user, order


def test_map_url():
    assert map_url(Dealer(name="A", latitude=41.31, longitude=69.24)) == "https://yandex.uz/maps/?pt=69.24,41.31&z=17&l=map"
    assert map_url(Dealer(name="JAC", address="Ташкент, Чиланзар 1")).startswith("https://yandex.uz/maps/?text=JAC%2C%20")
    assert map_url(Dealer(name="JAC")) is None


async def test_progress_and_buttons(db):
    user, order = await new_order(db)
    dealer = await db.get(Dealer, 1)
    dealer.address = "Чиланзар, 1"
    text = order_text(order, "ru")
    assert "✅ Оформлен\n⏳ Подтверждён\n▫️ Готов к выдаче\n▫️ Получен" in text
    kb = order_keyboard(order, "ru")
    assert kb.inline_keyboard[0][0].text == "🗺 Как добраться" and kb.inline_keyboard[0][0].url.startswith("https://yandex.uz")
    repo = OrderRepository(db)
    for status in ("CONFIRMED", "READY", "COMPLETED"):
        await repo.set_status(order, status)
    assert "✅ Готов к выдаче\n✅ Получен" in order_text(order, "ru")
    texts = [r[0].text for r in order_keyboard(order, "ru").inline_keyboard]
    assert "🗺 Как добраться" not in texts and "🔁 Повторить заказ" in texts


async def test_ready_message_with_venue_and_reminder(db):
    user, order = await new_order(db)
    dealer = await db.get(Dealer, 1)
    dealer.address, dealer.phone, dealer.latitude, dealer.longitude = "Чиланзар, 1", "+998712000000", 41.3, 69.2
    await OrderRepository(db).set_status(order, "CONFIRMED")
    await OrderRepository(db).set_status(order, "READY")
    await db.commit()
    bot = MagicMock()
    bot.send_message, bot.send_venue = AsyncMock(), AsyncMock()
    staff = User(id=9, telegram_id=99, language="ru")
    settings = MagicMock(admin_ids={99})
    await notify_status_change(bot, settings, db, order, actor=staff, role="admin")
    first = bot.send_message.call_args_list[0]
    assert first.args[0] == user.telegram_id and "готов — можно забирать" in first.args[1]
    assert "🏢 JAC Ташкент №1\n📌 Чиланзар, 1\n📞 +998712000000" in first.args[1]
    assert first.kwargs["reply_markup"].inline_keyboard[0][0].text == "🗺 Как добраться"
    bot.send_venue.assert_awaited_once()
    assert bot.send_venue.call_args.args[:3] == (user.telegram_id, 41.3, 69.2)

    bot.send_message.reset_mock()
    assert await remind_ready(bot, db) == 0  # меньше суток — рано
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert await remind_ready(bot, db, now=later) == 1
    assert "⏰ Напоминаем: заказ №" in bot.send_message.call_args.args[1]
    assert await remind_ready(bot, db, now=later + timedelta(days=1)) == 0  # напоминаем один раз


async def test_repeat_order(db):
    user, order = await new_order(db, qty=3)
    await OrderRepository(db).set_status(order, "CANCELLED")
    await db.commit()
    assert await CartRepository(db).repeat(user, order) == (1, [])
    [item] = await CartRepository(db).items(user)
    assert item.stock_id == 1 and item.quantity == 3

    await CartRepository(db).clear(user)
    (await db.get(Stock, 1)).quantity = 0  # у прежнего дилера закончилась — берём лучшую цену в регионе
    await db.commit()
    assert await CartRepository(db).repeat(user, order) == (1, [])
    [item] = await CartRepository(db).items(user)
    assert item.stock.dealer.name == "JAC Ташкент №2" and item.quantity == 3

    await CartRepository(db).clear(user)
    for stock in await db.scalars(select(Stock)):
        stock.quantity = 0
    await db.commit()
    assert await CartRepository(db).repeat(user, order) == (0, ["Масляный фильтр"])
