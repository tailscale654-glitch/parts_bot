from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, CarModel, Dealer, Node, Part, Region, Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.stocks import StockRepository
from app.keyboards.catalog import part_card_keyboard
from app.services.catalog import cart_text, money, part_card_text


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        tash = Region(id=1, code="tashkent_city", name_ru="Ташкент", name_en="Tashkent")
        sam = Region(id=2, code="samarkand", name_ru="Самарканд")
        part = Part(id=1, name_ru="Масляный фильтр", part_number="101001",
                    model=CarModel(name_ru="JAC JS4"), node=Node(name_ru="Двигатель"))
        dealers = [
            Dealer(id=1, region=tash, name="JAC Ташкент №1"),
            Dealer(id=2, region=tash, name="JAC Ташкент №2"),
            Dealer(id=3, region=tash, name="JAC Ташкент №3"),
            Dealer(id=4, region=sam, name="JAC Самарканд"),
            Dealer(id=5, region=tash, name="Закрытый", active=False),
        ]
        stocks = [
            Stock(id=1, part=part, dealer=dealers[0], price=Decimal(85000), quantity=12),
            Stock(id=2, part=part, dealer=dealers[1], price=Decimal(82000), quantity=4),
            Stock(id=3, part=part, dealer=dealers[2], price=Decimal(70000), quantity=0),  # дешевле, но нет в наличии
            Stock(id=4, part=part, dealer=dealers[3], price=Decimal(60000), quantity=5),  # другой регион
            Stock(id=5, part=part, dealer=dealers[4], price=Decimal(1000), quantity=9),  # неактивный дилер
        ]
        users = [User(id=1, telegram_id=1, language="ru", region=tash), User(id=2, telegram_id=2, language="en", region=sam)]
        s.add_all([part, *dealers, *stocks, *users])
        await s.commit()
        yield s
    await engine.dispose()


def test_money():
    assert money(Decimal("85000"), "ru") == "85 000 сум"
    assert money(Decimal("1905125.50"), "en") == "1 905 125.50 UZS"
    assert money(170000, "uz") == "170 000 so‘m"


async def test_offers_sorted_and_filtered_by_region(db):
    offers = await StockRepository(db).offers_in_region(1, 1)
    # в наличии и дешевле — выше; нет в наличии — внизу; чужой регион и неактивный дилер — не видны
    assert [o.dealer.name for o in offers] == ["JAC Ташкент №2", "JAC Ташкент №1", "JAC Ташкент №3"]
    assert await StockRepository(db).regions_elsewhere(1, 1) == 1


async def test_part_card(db):
    user = await db.get(User, 1)
    offers = await StockRepository(db).offers_in_region(1, 1)
    part = offers[0].part
    text = part_card_text(part, "ru", user.region, offers)
    assert "📍 ТАШКЕНТ" in text and "💰 82 000 сум" in text and "🟢 В наличии: 4 шт." in text and "🔴 Нет в наличии" in text
    assert text.index("Ташкент №2") < text.index("Ташкент №1") < text.index("Ташкент №3")
    kb = part_card_keyboard(part, 1, "ru", offers)
    buttons = [row[0].text for row in kb.inline_keyboard]
    assert buttons == ["🛒 JAC Ташкент №2 · 82 000 сум", "🛒 JAC Ташкент №1 · 85 000 сум", "◀️ Назад"]  # без «нет в наличии»


async def test_card_when_region_has_no_dealers(db):
    region = Region(id=3, code="khorezm", name_ru="Хорезм")
    part = await db.get(Part, 1)
    text = part_card_text(part, "ru", region, [], regions_elsewhere=2)
    assert "В вашем регионе этой детали пока нет" in text and "других регионах (2)" in text


async def test_cart_add_limit_and_change(db):
    user = await db.get(User, 1)
    cart = CartRepository(db)
    stock = await db.get(Stock, 2)  # в наличии 4
    for expected in (1, 2, 3, 4):
        assert await cart.add(user, stock) == (True, expected)
    assert await cart.add(user, stock) == (False, 4)  # больше остатка нельзя
    assert await cart.add(user, await db.get(Stock, 3)) == (False, 0)  # нет в наличии

    item = (await cart.items(user))[0]
    assert await cart.change(user, item.id, +1) is False
    assert await cart.change(user, item.id, -1) is True
    assert (await cart.items(user))[0].quantity == 3


async def test_cart_text_total_and_isolation(db):
    user, other = await db.get(User, 1), await db.get(User, 2)
    cart = CartRepository(db)
    await cart.add(user, await db.get(Stock, 1))
    await cart.add(user, await db.get(Stock, 1))
    await cart.add(user, await db.get(Stock, 2))
    text = cart_text(await cart.items(user), "ru")
    assert "2 × 85 000 сум = 170 000 сум" in text and "💰 Итого: 252 000 сум" in text

    item_id = (await cart.items(user))[0].id
    await cart.remove(other, item_id)  # чужую позицию удалить нельзя
    await cart.change(other, item_id, -5)
    assert len(await cart.items(user)) == 2

    stock = await db.get(Stock, 1)
    stock.quantity = 0  # после нового импорта деталь закончилась
    await db.commit()
    text = cart_text(await cart.items(user), "ru")
    assert "Сейчас нет в наличии" in text and "💰 Итого: 82 000 сум" in text

    await cart.clear(user)
    assert await cart.items(user) == []
