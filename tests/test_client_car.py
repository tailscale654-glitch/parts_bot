"""Автомобиль клиента: выбор при регистрации и каталог только для его модели."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, CarModel, Dealer, Node, Part, Region, Stock, User
from app.handlers import car as car_handlers
from app.handlers.catalog import models_view
from app.keyboards.car import CarCB
from app.services import cars
from app.services.excel_import import validate_any
from app.sync.carsale import write_xlsx
from tests.test_sync import row, snapshot


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        tash = Region(id=1, code="tashkent_city", name_ru="Ташкент")
        dealer = Dealer(id=1, region=tash, name="OOO «China Group»")
        rf8, t9, other = CarModel(name_ru="JAC RF8"), CarModel(name_ru="JAC T9"), CarModel(name_ru="Прочее")
        body, tools = Node(name_ru="Кузов"), Node(name_ru="Инструменты")
        parts = [
            Part(id=1, name_ru="Бампер AA3", part_number="A1", model=rf8, node=body, mod_codes="RF8-V9AA3"),
            Part(id=2, name_ru="Бампер HA0", part_number="A2", model=rf8, node=body, mod_codes="RF8-V9HA0"),
            Part(id=3, name_ru="Фильтр RF8", part_number="A3", model=rf8, node=body, mod_codes=""),
            Part(id=4, name_ru="Фара T9", part_number="B1", model=t9, node=body),
            Part(id=5, name_ru="Ключ", part_number="C1", model=other, node=tools),
        ]
        s.add_all([dealer, *parts, *[Stock(part=p, dealer=dealer, price=Decimal(1000), quantity=3) for p in parts]])
        s.add(User(id=1, telegram_id=11, language="ru", region=tash, phone="+998901112233"))
        await s.commit()
        yield s
    await engine.dispose()


def texts(kb):
    return [b.text for row_ in kb.inline_keyboard for b in row_]


def test_lists():
    assert "JAC RF8" in cars.models() and "Прочее" not in cars.models()
    assert cars.modifications("JAC RF8") == ["RF8-V9AA3", "RF8-V9HA0"] and len(cars.modifications("JAC T9")) == 1
    user = User(car_model="JAC RF8", car_modification="RF8-V9AA3", car_color="white")
    assert cars.car_text(user, "ru") == "JAC RF8 · RF8-V9AA3 · Белый" and cars.car_text(user, "uz").endswith("Oq")


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def edit_text(self, text, reply_markup=None):
        self.sent.append(("edit", text, reply_markup))

    async def answer(self, text, reply_markup=None):
        self.sent.append(("answer", text, reply_markup))


def callback():
    async def answer(*a, **k):
        return None
    return SimpleNamespace(message=FakeMessage(), answer=answer)


async def test_choose_car_then_catalog_shows_only_own_model(session):
    user = await session.get(User, 1)
    text, kb = await models_view(user, session)  # автомобиль не выбран — сначала выбор модели
    assert "модель вашего автомобиля" in text and "JAC RF8" in texts(kb)

    cb = callback()
    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC RF8")), user, session)
    assert "Цвет" in cb.message.sent[-1][1]
    await car_handlers.set_color(cb, CarCB(action="color", key="silver"), user, session)
    assert "Модификация" in cb.message.sent[-1][1]  # у RF8 их две — спрашиваем
    await car_handlers.set_mod(cb, CarCB(action="mod", i=0), user, session)
    assert (user.car_model, user.car_color, user.car_modification) == ("JAC RF8", "silver", "RF8-V9AA3")
    assert "JAC RF8 · RF8-V9AA3 · Серебристый" in cb.message.sent[-2][1]

    text, kb = await models_view(user, session)  # каталог: сразу категории своей модели, «Прочее», смена авто
    assert "Запчасти для JAC RF8" in text
    assert texts(kb) == ["Кузов", "🧰 Прочее (для всех моделей)", "🚗 Изменить автомобиль"]

    from app.database.repositories.catalog import CatalogRepository
    rf8 = await CatalogRepository(session).model_by_name("JAC RF8")
    body = (await CatalogRepository(session).list_nodes(rf8.id, "ru"))[0]
    names = [p.name_ru for p in await CatalogRepository(session).list_parts(rf8.id, body.id, "ru", 0, 50, "RF8-V9AA3")]
    assert names == ["Бампер AA3", "Фильтр RF8"]  # детали другой модификации не видны

    full_text, full_kb = await models_view(user, session, full=True)  # администратор / сотрудник — все модели
    assert set(texts(full_kb)) == {"JAC RF8", "JAC T9", "Прочее"}


async def test_unknown_modification_shows_all_and_single_mod_skips_step(session):
    user = await session.get(User, 1)
    cb = callback()
    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC T9")), user, session)
    await car_handlers.set_color(cb, CarCB(action="color", key="black"), user, session)
    assert "Автомобиль: JAC T9 · Чёрный" in cb.message.sent[-2][1]  # у T9 одна модификация — шаг пропущен

    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC RF8")), user, session)
    await car_handlers.set_color(cb, CarCB(action="color", key="red"), user, session)
    await car_handlers.set_mod(cb, CarCB(action="mod", i=-1), user, session)  # «Не знаю»
    assert user.car_modification is None
    from app.database.repositories.catalog import CatalogRepository
    rf8 = await CatalogRepository(session).model_by_name("JAC RF8")
    assert await CatalogRepository(session).count_parts(rf8.id, 1, user.car_modification) == 3

    bad = callback()
    await car_handlers.set_model(bad, CarCB(action="model", i=999), user, session)  # подделанная кнопка
    assert bad.message.sent == [] and user.car_model == "JAC RF8"


def test_import_keeps_modification_codes(tmp_path):
    path = write_xlsx(snapshot([row(1, "A1", "BUMPER", "OOO «China Group»", model="RF8-V9AA3"),
                                row(1, "A1", "BUMPER", "OOO «China Group»", model="RF8-V9AA3"),
                                row(1, "A2", "FILTER", "OOO «China Group»", model="RF8-V9AA3,V9HA0"),
                                row(1, "A3", "BELT", "OOO «China Group»", model="M3")]), tmp_path / "w.xlsx")
    rows, *_ = validate_any(path, [Region(id=1, code="tashkent_city", name_ru="Т")])
    got = {r.part_number: r.mod_codes for r in rows}
    assert got == {"A1": "RF8-V9AA3", "A2": "RF8-V9AA3,RF8-V9HA0", "A3": ""}


def test_order_card_shows_car():
    from datetime import datetime, timezone

    from app.database.models import Order
    from app.services.orders import order_text

    user = User(first_name="Азиз", phone="+998901112233", region=None)
    order = Order(id=10001, user=user, dealer=Dealer(name="OOO «China Group»"), status="NEW",
                  total_amount=Decimal(1000), car="JAC RF8 · RF8-V9AA3 · Белый",
                  created_at=datetime.now(timezone.utc))
    order.items = []
    assert "🚗 Автомобиль: JAC RF8 · RF8-V9AA3 · Белый" in order_text(order, "ru", for_admin=True)
    assert "Автомобиль" not in order_text(order, "ru")  # клиенту — его же данные не повторяем
