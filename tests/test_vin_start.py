"""VIN при регистрации: телефон → VIN (сканер в витрине, фото или текст) → машина из CarSale CRM → каталог.
CRM подменена (tests/test_carsale_crm.StubCRM) — в настоящую не ходим."""
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.database.models import User
from app.handlers import car as car_handlers
from app.handlers import vin as vin_handlers
from app.handlers.start import next_step
from app.handlers.vin import VinCB, VinStates, vin_wanted
from app.keyboards.car import CarCB
from app.services import carsale_crm, cars
from tests.test_carsale_crm import VIN, StubCRM, sold
from tests.test_client_car import session, texts  # noqa: F401 — фикстура базы с клиентом id=1


class Sent:
    def __init__(self, log, text, kb=None):
        self.log, self.text, self.kb = log, text, kb

    async def edit_text(self, text, reply_markup=None):
        self.log.append(("edit", text, reply_markup))

    async def delete(self):
        self.log.append(("delete", self.text, None))


class FakeMessage:
    def __init__(self, text=None):
        self.text, self.photo, self.document, self.sent = text, None, None, []

    async def answer(self, text, reply_markup=None):
        self.sent.append(("answer", text, reply_markup))
        return Sent(self.sent, text, reply_markup)

    async def edit_text(self, text, reply_markup=None):
        self.sent.append(("edit", text, reply_markup))


def callback(message=None):
    async def answer(*a, **k):
        return None
    return SimpleNamespace(message=message or FakeMessage(), answer=answer)


@pytest.fixture
def state():
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=11, user_id=11))


@pytest.fixture
def crm():
    stub = StubCRM({VIN: sold(VIN), "LJ166A339S2205968": sold("LJ166A339S2205968")})
    carsale_crm.set_crm(stub)
    yield stub
    carsale_crm.set_crm(None)


async def test_registration_asks_phone_then_vin(session):  # noqa: F811
    user = await session.get(User, 1)
    user.phone = None
    msg = FakeMessage()
    await next_step(msg, user, session)
    assert "номер телефона" in msg.sent[-1][1]  # телефон теперь раньше автомобиля
    user.phone = "+998901112233"
    await next_step(msg, user, session)
    assert "VIN вашего автомобиля" in msg.sent[-1][1]
    assert texts(msg.sent[-1][2])[-1] == "🚗 Выбрать модель вручную"


async def test_vin_from_carsale_fills_the_car(session, state, crm):  # noqa: F811
    user = await session.get(User, 1)
    assert await vin_wanted(FakeMessage(VIN), user, state)  # машины нет — VIN из чата ловим
    msg = FakeMessage(" lj166a257t4020777 ")
    await vin_handlers.vin_text(msg, user, session, state)
    card = msg.sent[-1][1]
    assert "Нашёл ваш автомобиль" in card and "JAC JS8 · Чёрный" in card and "Двигатель №: T3604334" in card
    assert texts(msg.sent[-1][2]) == ["✅ Да, это моя", "✏️ Другой VIN"]
    assert user.car_model is None  # пока не подтвердил — ничего не меняем

    cb = callback()
    await vin_handlers.vin_confirm(cb, VinCB(action="ok", vin=VIN), user, session, state)
    assert (user.car_model, user.car_color, user.car_vin, user.car_engine, user.car_trim) == \
        ("JAC JS8", "black", VIN, "T3604334", "JAC JS8")
    assert "Автомобиль сохранён" in cb.message.sent[0][1]
    assert cars.car_with_vin(user, "ru") == f"JAC JS8 · Чёрный · VIN {VIN} · двиг. T3604334"
    assert not await vin_wanted(FakeMessage(VIN), user, state)  # машина есть — VIN в чате уже не перехватываем

    # подделанная кнопка с чужим VIN, которого нет в CRM, — ничего не сохраняем
    await vin_handlers.vin_confirm(callback(), VinCB(action="ok", vin="LJ1ZZZZZZZZ000000"), user, session, state)
    assert user.car_vin == VIN


async def test_vin_not_sold_here_then_manual_model(session, state, crm):  # noqa: F811
    user = await session.get(User, 1)
    other = "LJ12EKR17N4000123"
    msg = FakeMessage(other)
    await vin_handlers.vin_text(msg, user, session, state)
    assert "Не нашёл VIN" in msg.sent[-1][1] and texts(msg.sent[-1][2])[0] == "🚗 Выбрать модель вручную"

    cb = callback()
    await car_handlers.set_model(cb, CarCB(action="model", i=cars.models().index("JAC T8")), user, session)
    await car_handlers.set_color(cb, CarCB(action="color", i=0), user, session, state)
    assert (user.car_model, user.car_color, user.car_vin, user.car_engine) == ("JAC T8", "white", other, None)


async def test_crm_down_and_change_car(session, state):  # noqa: F811
    carsale_crm.set_crm(StubCRM(down=True))
    try:
        user = await session.get(User, 1)
        msg = FakeMessage(VIN)
        await vin_handlers.vin_text(msg, user, session, state)
        assert "не получается проверить" in msg.sent[-1][1]
        assert (await state.get_data())["pending_vin"] == VIN
    finally:
        carsale_crm.set_crm(None)

    # «🚗 Изменить автомобиль» → экран VIN и ожидание номера; кнопка меню выходит из ожидания
    user.car_model, user.car_color = "JAC T9", "white"
    cb = callback()
    await car_handlers.start_car(cb, user, state)
    assert "VIN вашего автомобиля" in cb.message.sent[-1][1]
    assert await state.get_state() == VinStates.wait.state
    assert await vin_wanted(FakeMessage(VIN), user, state)
    from app.handlers.start import leave_search
    await leave_search(state)
    assert await state.get_state() is None
