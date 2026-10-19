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


def test_lists_from_commercial_offer():
    assert cars.models() == ["JAC M3", "JAC M4", "JAC Sunray", "JAC T8", "JAC T9", "JAC JS8", "JAC RF8"]
    assert cars.modifications("JAC M3") == ["passenger", "van"] and cars.modifications("JAC T9") == []
    assert cars.colors("JAC T9") == ["white", "black", "silver", "metallic_gray", "star_gray"]
    assert cars.colors("JAC RF8") == ["white", "gray", "blue"]
    user = User(car_model="JAC M4", car_color="silver")
    assert cars.catalog_model(user) == "JAC M4 Luxe" and cars.car_text(user, "uz") == "JAC M4 · Kumushrang"
    user = User(car_model="JAC M3", car_modification="van", car_color="white")
    assert cars.car_text(user, "ru") == "JAC M3 · VAN (фургон) · Белый"


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
    assert "модель вашего автомобиля" in text and texts(kb) == cars.models()

    cb = callback()
    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC Sunray")), user, session)
    assert "Комплектация" in cb.message.sent[-1][1]
    assert texts(cb.message.sent[-1][2]) == ["Микроавтобус (16 мест)", "VAN (фургон)"]
    await car_handlers.set_mod(cb, CarCB(action="mod", i=1), user, session)
    assert texts(cb.message.sent[-1][2]) == ["Белый", "Чёрный", "Серебристый", "Серый", "Серый металлик"]
    await car_handlers.set_color(cb, CarCB(action="color", i=4), user, session)
    assert (user.car_model, user.car_modification, user.car_color) == ("JAC Sunray", "van", "metallic_gray")
    assert "JAC Sunray · VAN (фургон) · Серый металлик" in cb.message.sent[-2][1]

    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC RF8")), user, session)
    assert "Цвет" in cb.message.sent[-1][1]  # у RF8 одна комплектация — шаг пропущен
    await car_handlers.set_color(cb, CarCB(action="color", i=2), user, session)
    assert (user.car_modification, user.car_color) == (None, "blue")

    text, kb = await models_view(user, session)  # каталог: сразу категории своей модели, «Прочее», смена авто
    assert "Запчасти для JAC RF8 · Синий" in text
    assert texts(kb) == ["Кузов", "🧰 Прочее (для всех моделей)", "🚗 Изменить автомобиль"]

    from app.database.repositories.catalog import CatalogRepository
    repo = CatalogRepository(session)
    rf8 = await repo.model_by_name("JAC RF8")
    assert await repo.count_parts(rf8.id, 1, cars.carsale_code(user)) == 3  # все детали RF8, без T9

    full_text, full_kb = await models_view(user, session, full=True)  # администратор / сотрудник — все модели
    assert set(texts(full_kb)) == {"JAC RF8", "JAC T9", "Прочее"}


async def test_bad_buttons_ignored_and_no_parts_message(session):
    user = await session.get(User, 1)
    bad = callback()
    await car_handlers.set_model(bad, CarCB(action="model", i=999), user, session)  # подделанная кнопка
    await car_handlers.set_color(bad, CarCB(action="color", i=0), user, session)  # цвет до модели
    assert bad.message.sent == [] and user.car_model is None

    cb = callback()
    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC T8")), user, session)
    await car_handlers.set_color(cb, CarCB(action="color", i=9), user, session)  # нет такого цвета у T8
    assert user.car_color is None
    await car_handlers.set_color(cb, CarCB(action="color", i=2), user, session)
    text, kb = await models_view(user, session)  # запчастей T8 нет — честно говорим, предлагаем «Прочее»
    assert "нет запчастей" in text and texts(kb) == ["🧰 Прочее (для всех моделей)", "🚗 Изменить автомобиль"]


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
                  total_amount=Decimal(1000), car="JAC M3 · VAN (фургон) · Белый",
                  created_at=datetime.now(timezone.utc))
    order.items = []
    assert "🚗 Автомобиль: JAC M3 · VAN (фургон) · Белый" in order_text(order, "ru", for_admin=True)
    assert "Автомобиль" not in order_text(order, "ru")  # клиенту — его же данные не повторяем


def test_change_car_button_routes_to_handler():
    """«🚗 Изменить автомобиль» из профиля — и новая кнопка, и из старых сообщений (car:start:0:)."""
    from aiogram import F

    from app.keyboards.main import profile_keyboard

    data = profile_keyboard("ru").inline_keyboard[0][0].callback_data
    flt = F.data.startswith("car:start")
    for value in (data, "car:start:0:", "car:start"):
        assert flt.resolve(SimpleNamespace(data=value))
    assert not flt.resolve(SimpleNamespace(data=CarCB(action="model", i=1).pack()))
