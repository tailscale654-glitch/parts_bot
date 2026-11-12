"""ТО: регламент, пробег, напоминания и набор деталей для ТО в корзину."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, CarModel, CartItem, Dealer, MileageRecord, Node, Part, Region, Stock, User
from app.handlers import service as svc
from app.handlers.service import ServiceCB
from app.services import maintenance as m


def test_schedule():
    assert m.next_service("JAC T8", 9_200) == m.Due(1, 10_000, 800)
    assert m.next_service("JAC T8", 20_000) == m.Due(2, 20_000, 0)
    assert m.next_service("JAC T8", 0) == m.Due(1, 10_000, 10_000)
    base = ["engine_oil", "oil_filter", "drain_gasket", "cabin_filter"]
    assert m.kinds_for("JAC T8", 1) == base
    assert m.kinds_for("JAC T8", 2) == base + ["air_filter"]
    assert m.kinds_for("JAC T8", 3) == base + ["spark_plug"]
    assert m.kinds_for("JAC T8", 4) == base + ["air_filter", "fuel_filter"]
    m.MODEL_PLAN["JAC T9"] = {"interval": 15_000, "every": {"air_filter": 15_000}}
    try:
        assert m.next_service("JAC T9", 14_000) == m.Due(1, 15_000, 1_000)
        assert "air_filter" in m.kinds_for("JAC T9", 1)
    finally:
        m.MODEL_PLAN.clear()


@pytest.mark.parametrize("mileage, reminded, expected", [
    (9_200, None, m.Due(1, 10_000, 800)),  # скоро
    (9_200, 10_000, None),  # уже напомнили
    (8_500, None, None),  # ещё рано
    (10_500, None, m.Due(1, 10_000, -500)),  # прошло, напоминания не было
    (14_000, None, None),  # прошло давно (перебег больше 3000) — ждём следующего
    (19_300, 10_000, m.Due(2, 20_000, 700)),
])
def test_due_reminder(mileage, reminded, expected):
    user = User(car_model="JAC T8", car_mileage=mileage, service_reminded_km=reminded)
    assert m.due_reminder(user) == expected


@pytest.mark.parametrize("text, km", [
    ("23400", 23400), ("23 400", 23400), ("23 400 км", 23400), ("23.400", 23400), ("23,4 тыс", 23400),
    ("23к", 23000), ("150000 km", 150000), (" 7 200 ", 7200),
    ("abc", None), ("0", None), ("23,4", None), ("1 000 000 000", None), ("LJ12EKR17N4000123", None), ("", None),
])
def test_parse_mileage(text, km):
    assert m.parse_mileage(text) == km


@pytest.mark.parametrize("en, ru, kind", [
    ("engine oil filter", "Масляный фильтр двигателя", "oil_filter"),
    ("engine oil filter element", "Элемент масляного фильтра", "oil_filter"),
    ("engine oil filter connecting pipe", "Соединительная трубка масляного фильтра", None),
    ("oil filter module", "Модуль масляного фильтра", None),
    ("air filter element", "Элемент воздушного фильтра", "air_filter"),
    ("air filter assembly", "Воздушный фильтр в сборе (корпус)", None),  # корпус — не расходник
    ("air filter lower housing", "Нижний корпус воздушного фильтра", None),
    ("carbon tank air filter", "Воздушный фильтр адсорбера", None),
    ("a/c filter element", "Фильтр салона (кондиционера)", "cabin_filter"),
    ("CABIN AIR FILTER", "Фильтр воздушный салона", "cabin_filter"),  # не воздушный фильтр двигателя
    ("AIR FILTER ELEMENT", None, "air_filter"),
    ("spark plug", "Свеча зажигания", "spark_plug"),
    ("gasoline filter assy", "Топливный фильтр в сборе", "fuel_filter"),
    ("gasket(oil drain plug)", "Прокладка (сливной пробки масла)", "drain_gasket"),
    ("drain screw plug washer", "Шайба сливной пробки", "drain_gasket"),
    ("drain screw plug", "Пробка сливная", None),
    ("roof evaporator drain pipe 1", "Трубка дренажная потолочного испарителя 1", None),
    ("engine oil dipstick", "Щуп уровня масла двигателя", None),
    (None, "Масло моторное 5W-30 4 л", "engine_oil"),
    ("front bumper", "Бампер передний", None),
])
def test_kind_of(en, ru, kind):
    assert m.kind_of(Part(name_en=en, name_ru=ru)) == kind


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        tash = Region(id=1, code="tashkent_city", name_ru="Ташкент")
        a = Dealer(id=1, region=tash, name="China Group")
        b = Dealer(id=2, region=tash, name="Asiamotor")
        wh = Dealer(id=3, region=tash, name="Склад JAC", is_warehouse=True)
        t8, other = CarModel(name_ru="JAC T8"), CarModel(name_ru="Прочее")
        node = Node(name_ru="ТО")

        def part(i, en, ru, model=t8):
            return Part(id=i, name_en=en, name_ru=ru, part_number=f"P{i}", model=model, node=node)
        oil_f, air_el, air_box, cabin, plug, gasket, oil = (
            part(1, "engine oil filter", "Масляный фильтр"), part(2, "air filter element", "Элемент воздушного фильтра"),
            part(3, "air filter assembly", "Воздушный фильтр в сборе (корпус)"),
            part(4, "a/c filter element", "Фильтр салона (кондиционера)"), part(5, "spark plug", "Свеча зажигания"),
            part(6, "gasket(oil drain plug)", "Прокладка сливной пробки"),
            part(7, None, "Масло моторное 5W-30 4 л", model=other))
        s.add_all([a, b, wh, oil_f, air_el, air_box, cabin, plug, gasket, oil,
                   Stock(part=oil_f, dealer=a, price=Decimal(60000), quantity=5),
                   Stock(part=oil_f, dealer=b, price=Decimal(50000), quantity=5),  # дешевле, но набора у него нет
                   Stock(part=cabin, dealer=a, price=Decimal(80000), quantity=2),
                   Stock(part=gasket, dealer=a, price=Decimal(5000), quantity=10),
                   Stock(part=air_box, dealer=a, price=Decimal(900000), quantity=1),
                   Stock(part=air_el, dealer=wh, price=Decimal(120000), quantity=3),  # только на складе JAC
                   Stock(part=plug, dealer=b, price=Decimal(30000), quantity=3)])  # 3 шт., а нужно 4
        s.add(User(id=1, telegram_id=11, language="ru", region=tash, phone="+998901112233", car_model="JAC T8",
                   car_color="white", created_at=datetime.now(timezone.utc) - timedelta(days=5)))
        await s.commit()
        yield s
    await engine.dispose()


async def test_kit_for_service_2_goes_to_cart(session):
    user = await session.get(User, 1)
    kit = await m.build_kit(session, user, 2)
    assert kit.dealer.name == "China Group"  # у него больше всего позиций набора
    got = {line.kind: (line.part.part_number if line.part else None, line.stock.dealer.name if line.stock else None)
           for line in kit.lines}
    assert got == {"engine_oil": ("P7", None), "oil_filter": ("P1", "China Group"), "drain_gasket": ("P6", "China Group"),
                   "cabin_filter": ("P4", "China Group"), "air_filter": ("P2", "Склад JAC")}  # корпус не попал
    assert kit.total == Decimal(60000 + 5000 + 80000 + 120000)
    added, failed = await m.add_kit_to_cart(session, user, kit)
    assert len(added) == 4 and failed == []
    items = (await session.scalars(__import__("sqlalchemy").select(CartItem))).unique().all()
    assert sorted((i.stock.part.part_number, i.quantity, i.pickup_dealer_id) for i in items) == \
        [("P1", 1, None), ("P2", 1, 1), ("P4", 1, None), ("P6", 1, None)]  # склад — с выдачей у China Group
    await m.add_kit_to_cart(session, user, await m.build_kit(session, user, 2))  # повторно — не удваиваем
    assert sum(i.quantity for i in (await session.scalars(__import__("sqlalchemy").select(CartItem))).unique().all()) == 4

    kit3 = await m.build_kit(session, user, 3)  # свечей нужно 4, у дилера 3 — в наличии нет
    assert next(line for line in kit3.lines if line.kind == "spark_plug").stock is None


class Msg:
    def __init__(self):
        self.sent = []

    async def answer(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))

    async def edit_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


def cb():
    async def answer(*a, **k):
        return None
    return SimpleNamespace(message=Msg(), answer=answer)


def buttons(kb):
    return [b.text for row in kb.inline_keyboard for b in row]


async def test_mileage_question_answer_and_reminder(session):
    user = await session.get(User, 1)
    text, kb = svc.service_view(user)
    assert "Укажите пробег" in text and buttons(kb) == ["✏️ Указать пробег"]

    c = cb()
    await svc.ask(c, user, session)
    assert "Какой сейчас пробег" in c.message.sent[0][0] and buttons(c.message.sent[0][1]) == ["⏰ Не сейчас"]
    assert await svc.mileage_wanted(None, user)  # теперь число в чате — пробег

    msg = Msg()
    await svc.typed_km(SimpleNamespace(text="9 300 км", answer=msg.answer), user, session)
    assert user.car_mileage == 9300 and "Скоро ТО-1" in msg.sent[0][0] and "осталось ~700 км" in msg.sent[0][0]
    assert buttons(msg.sent[0][1]) == ["🛒 Набор для ТО-1"] and user.service_reminded_km == 10_000
    assert not await svc.mileage_wanted(None, user)  # ответил — числа снова идут как обычно

    text, kb = svc.service_view(user)
    assert "Пробег: 9 300 км" in text and "ТО-1 на 10 000 км" in text and "• масляный фильтр" in text

    # история пробега → кнопки с примерным пробегом
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    for record in (await session.scalars(__import__("sqlalchemy").select(MileageRecord))).all():
        record.created_at = month_ago  # ответ «9 300 км» был месяц назад…
    session.add(MileageRecord(user_id=1, km=5300, created_at=month_ago - timedelta(days=20)))  # …а за 20 дней до него — 5 300
    user.car_mileage_at = month_ago
    await session.commit()
    guess = await m.estimate(session, user)  # 4000 км за 20 дней → +6 000 за 30 дней → ≈ 15 300
    assert guess == 15_500
    c = cb()
    await svc.ask(c, user, session)
    assert buttons(c.message.sent[0][1]) == ["≈ 14 500 км", "≈ 15 500 км", "≈ 16 500 км", "⏰ Не сейчас"]
    c = cb()
    await svc.pick_km(c, ServiceCB(action="km", n=20_500), user, session)
    assert "Пора ТО-2" in c.message.sent[0][0]

    c = cb()
    await svc.later(c, user, session)
    assert not m.asked_recently(user)


async def test_kit_button_puts_kit_in_cart(session):
    user = await session.get(User, 1)
    c = cb()
    await svc.kit(c, ServiceCB(action="kit", n=2), user, session)
    text = c.message.sent[0][0]
    assert "Набор для ТО-2 в корзине (China Group)" in text
    assert "• масляный фильтр — P1, 60 000 сум" in text and "под заказ со склада" in text
    assert "Нет в наличии в вашем регионе: моторное масло" in text
    assert "КОРЗИНА" in c.message.sent[1][0]
    c = cb()
    await svc.kit(c, ServiceCB(action="kit", n=999), user, session)  # подделанная кнопка
    assert c.message.sent == []


async def test_monthly_mileage_round(session):
    user = await session.get(User, 1)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    night = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)  # 01:00 в Ташкенте
    assert await svc.ask_mileage_round(bot, session, now=night) == 0
    day = datetime.now(timezone.utc).replace(hour=7)  # 12:00 в Ташкенте
    assert await svc.ask_mileage_round(bot, session, now=day) == 1
    assert "Какой сейчас пробег" in bot.send_message.call_args.args[1]
    assert user.mileage_asked_at is not None
    assert await svc.ask_mileage_round(bot, session, now=day) == 0  # уже спросили — следующий раз через месяц
