"""ТО автомобиля клиента: регламент, пробег, напоминания и набор деталей для ТО.

РЕГЛАМЕНТ (что и когда меняют) — таблицы ниже, их можно править без знания Python: меняйте только числа.
Сейчас стоят ТИПОВЫЕ значения JAC (ТО каждые 10 000 км; фильтр воздушный — через ТО и т. д.).
Официальный регламент JAC Motors Toshkent может отличаться — сверьте с сервисом и поправьте цифры.

Набор для ТО подбирается из каталога модели клиента по названиям деталей («Масляный фильтр»,
«Элемент воздушного фильтра», «Фильтр салона (кондиционера)», «Свеча зажигания»…). Если для модели нужно
задать точный номер детали — впишите его в KIT_PARTS. Менеджер видит VIN в заказе и проверит подбор.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Dealer, MileageRecord, Part, Stock, User
from app.database.repositories.cart import CartRepository, can_pickup
from app.database.repositories.stocks import StockRepository
from app.services import cars

# ---------- регламент ----------
INTERVAL_KM = 10_000  # ТО-1 на 10 000 км, ТО-2 на 20 000 км, …
REMIND_BEFORE_KM = 1_000  # напоминаем, когда до ТО осталось не больше
OVERDUE_KM = 3_000  # ТО прошло, но напоминания не было — напомним, если перебег не больше этого
ASK_EVERY_DAYS = 30  # раз в месяц спрашиваем пробег

# что меняют и как часто (км). Деталь войдёт в набор, если её номер ТО кратен: 20 000 — на ТО-2, ТО-4, …
EVERY_KM = {
    "engine_oil": 10_000,
    "oil_filter": 10_000,
    "drain_gasket": 10_000,
    "cabin_filter": 10_000,
    "air_filter": 20_000,
    "spark_plug": 30_000,
    "fuel_filter": 40_000,
}
# сколько штук в наборе (свечей — по числу цилиндров)
QUANTITY = {"spark_plug": 4}

# свой регламент для модели, например {"JAC T8": {"interval": 10000, "every": {"fuel_filter": 20000}}}
MODEL_PLAN: dict[str, dict] = {}

# точные номера деталей набора для модели (если автоподбор по названию ошибается),
# например {"JAC T8": {"oil_filter": "1017100GD050"}}
KIT_PARTS: dict[str, dict[str, str]] = {}

KINDS = list(EVERY_KM)  # порядок в сообщениях

# как узнать деталь по названию: (что должно быть, чего не должно быть) — по русскому и английскому названию
_RULES = {
    "oil_filter": (r"oil filter|масл\w* фильтр|фильтр\w* масл",
                   r"pipe|connect|module|housing|bracket|seat|cooler|suction|gasket|base|трубк|модул|корпус|кронштейн"
                   r"|радиатор|маслоприём|маслоприем|сетк|прокладк|основан"),
    "cabin_filter": (r"a/c filter|ac filter|cabin (air )?filter|air[- ]?condition\w* filter|pollen|фильтр\w*.{0,15}салон"
                     r"|салонн\w* фильтр|фильтр кондиционер",
                     r"housing|cover|drier|dryer|корпус|крышк|осушит"),
    "air_filter": (r"air filter|air cleaner|воздушн\w* фильтр|фильтр\w* воздушн",
                   r"housing|pipe|sleeve|outlet|inlet|insulat|carbon|canister|bracket|cover|cabin|корпус|патрубок|виброизол"
                   r"|адсорбер|кронштейн|крышк|салон"),
    "spark_plug": (r"spark\w* plug|свеч\w* зажиган", r"cable|wire|cap|coil|провод|колпач|катушк"),
    "fuel_filter": (r"fuel filter|gasoline filter|diesel filter|топливн\w* фильтр|фильтр\w* топлив",
                    r"bracket|pipe|sensor|housing|seat|heater|кронштейн|трубк|датчик|корпус|подогрев"),
    "drain_gasket": (r"drain\w*.{0,20}(washer|gasket|seal)|oil drain bolt gasket|(washer|gasket|seal\w*).{0,20}drain"
                     r"|сливн\w* пробк|прокладк\w* сливн|шайб\w* сливн",
                     r"evaporator|испарител|дренаж|drain pipe|plug assy|пробка сливная$"),
    "engine_oil": (r"engine oil \d|motor oil|моторн\w* масл|масло моторн|\b\d{1,2}w-?\d{2}\b",
                   r"filter|dipstick|cooler|pan|pressure|filler|pump|seal|фильтр|щуп|радиатор|поддон|давлен|горлов|насос"
                   r"|сальник"),
}


def kind_of(part: Part) -> str | None:
    """Вид расходника по названию детали (или None — не расходник ТО). Исключения смотрим в обоих названиях:
    «air filter assembly» по-русски «Воздушный фильтр в сборе (корпус)» — это корпус, а не фильтр."""
    text = f"{part.name_en or ''} | {part.name_ru or ''}".lower()
    for kind, (yes, no) in _RULES.items():
        if re.search(yes, text):
            return None if re.search(no, text) else kind
    return None


def plan(model: str | None) -> tuple[int, dict[str, int]]:
    custom = MODEL_PLAN.get(model or "", {})
    return custom.get("interval", INTERVAL_KM), {**EVERY_KM, **custom.get("every", {})}


def kinds_for(model: str | None, number: int) -> list[str]:
    """Что меняют на ТО с этим номером (ТО-1, ТО-2, …)."""
    interval, every = plan(model)
    km = number * interval
    return [k for k in KINDS if every.get(k) and km % every[k] == 0]


@dataclass(frozen=True)
class Due:
    number: int  # номер ТО
    km: int  # на каком пробеге
    left: int  # сколько осталось (отрицательное — уже пора)


def next_service(model: str | None, mileage: int) -> Due:
    """Ближайшее ТО впереди (на пробеге ровно 20 000 — ТО-2 «сейчас»)."""
    interval, _ = plan(model)
    number = max(1, -(-mileage // interval))  # округление вверх
    return Due(number, number * interval, number * interval - mileage)


def due_reminder(user: User) -> Due | None:
    """Пора напомнить о ТО: скоро (≤ 1000 км) или только что прошло (перебег ≤ 3000 км) и об этом ТО ещё не писали."""
    if user.car_mileage is None or not user.car_model:
        return None
    interval, _ = plan(user.car_model)
    upcoming = next_service(user.car_model, user.car_mileage)
    passed_number = user.car_mileage // interval
    candidates = [upcoming] if upcoming.left <= REMIND_BEFORE_KM else []
    if passed_number >= 1 and user.car_mileage - passed_number * interval <= OVERDUE_KM:
        candidates.append(Due(passed_number, passed_number * interval, passed_number * interval - user.car_mileage))
    for due in candidates:
        if (user.service_reminded_km or 0) < due.km:
            return due
    return None


# ---------- пробег ----------

def parse_mileage(text: str | None) -> int | None:
    """«23 400», «23400 км», «23,4 тыс», «23.4k» → 23400. Не похоже на пробег — None."""
    raw = (text or "").lower().replace(" ", " ").strip()
    m = re.fullmatch(r"(\d{1,3}(?:[ .,]\d{3})+|\d+)(?:[.,](\d))?\s*(тыс\.?|т\.?|k|к|ming)?\s*(км|km)?\.?", raw)
    if not m:
        return None
    whole = int(re.sub(r"[ .,]", "", m.group(1)))
    if m.group(3):  # «23,4 тыс»
        whole = whole * 1000 + (int(m.group(2)) * 100 if m.group(2) else 0)
    elif m.group(2):
        return None  # «23,4» без «тыс» — непонятно
    return whole if 0 < whole < 2_000_000 else None


async def save_mileage(session: AsyncSession, user: User, km: int) -> None:
    now = datetime.now(timezone.utc)
    user.car_mileage, user.car_mileage_at = km, now
    session.add(MileageRecord(user_id=user.id, km=km, created_at=now))
    await session.commit()


async def estimate(session: AsyncSession, user: User) -> int | None:
    """Примерный пробег сейчас по прошлым записям (нужно ≥ 2 записи с разницей ≥ 14 дней)."""
    if user.car_mileage is None or user.car_mileage_at is None:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=365)
    rows = (await session.scalars(select(MileageRecord).where(
        MileageRecord.user_id == user.id, MileageRecord.created_at >= since).order_by(MileageRecord.created_at))).all()
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    days = (_aware(last.created_at) - _aware(first.created_at)).days
    if days < 14 or last.km <= first.km:
        return None
    per_day = (last.km - first.km) / days
    passed = (datetime.now(timezone.utc) - _aware(user.car_mileage_at)).days
    return round((user.car_mileage + per_day * passed) / 500) * 500


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite в тестах хранит без пояса


def asked_recently(user: User, days: int = 3) -> bool:
    """Спросили пробег и ещё не ответили — следующее число в чате считаем пробегом."""
    if user.mileage_asked_at is None:
        return False
    asked = _aware(user.mileage_asked_at)
    answered = user.car_mileage_at is not None and _aware(user.car_mileage_at) >= asked
    return not answered and datetime.now(timezone.utc) - asked < timedelta(days=days)


# ---------- набор для ТО ----------

@dataclass
class KitLine:
    kind: str
    part: Part | None = None
    stock: Stock | None = None  # у дилера региона или на складе JAC
    pickup: Dealer | None = None  # для предзаказа со склада — где забрать
    qty: int = 1

    @property
    def price(self) -> Decimal | None:
        return self.stock.price * self.qty if self.stock else None


@dataclass
class Kit:
    number: int
    km: int
    dealer: Dealer | None = None  # где забрать большую часть набора
    lines: list[KitLine] = field(default_factory=list)

    @property
    def found(self) -> list[KitLine]:
        return [line for line in self.lines if line.stock]

    @property
    def missing(self) -> list[KitLine]:
        return [line for line in self.lines if not line.stock]

    @property
    def total(self) -> Decimal:
        return sum((line.price for line in self.found), Decimal(0))


async def _candidates(session: AsyncSession, user: User, kinds: list[str]) -> dict[str, list[Part]]:
    """Детали каталога модели клиента по видам (масло ищем и в «Прочее» — оно для всех моделей)."""
    from app.services.import_mapping import ALL_MODELS

    model_name = cars.catalog_model(user)
    names = [model_name, *ALL_MODELS] if "engine_oil" in kinds else [model_name]
    parts = (await session.scalars(
        select(Part).join(CarModel, CarModel.id == Part.model_id)
        .where(CarModel.name_ru.in_(names), CarModel.active.is_(True), Part.active.is_(True)))).unique().all()
    exact = KIT_PARTS.get(user.car_model or "", {})
    found: dict[str, list[Part]] = {k: [] for k in kinds}
    for part in parts:
        for kind, number in exact.items():
            if kind in found and part.part_number == number:
                found[kind].insert(0, part)
        kind = kind_of(part)
        if kind in found and kind not in exact and (kind == "engine_oil" or part.model.name_ru == model_name):
            found[kind].append(part)
    return found


async def build_kit(session: AsyncSession, user: User, number: int) -> Kit:
    """Набор для ТО-N: для каждого расходника — лучшая деталь в наличии в регионе клиента.
    Всё стараемся взять у одного дилера (того, у кого есть больше позиций набора); чего у него нет — у другого
    дилера региона или со склада JAC (предзаказ с выдачей у этого дилера)."""
    interval, _ = plan(user.car_model)
    kit = Kit(number=number, km=number * interval)
    kinds = kinds_for(user.car_model, number)
    found = await _candidates(session, user, kinds)
    stocks = StockRepository(session)
    offers: dict[str, list[tuple[Part, list[Stock]]]] = {}
    score: dict[int, tuple[int, Decimal]] = {}  # дилер → (сколько видов набора есть, сумма)
    dealers: dict[int, Dealer] = {}
    for kind in kinds:
        offers[kind] = []
        seen: set[int] = set()
        for part in found[kind]:
            local = [s for s in await stocks.offers_in_region(part.id, user.region_id) if s.quantity >= QUANTITY.get(kind, 1)]
            offers[kind].append((part, local))
            for s in local:
                dealers[s.dealer_id] = s.dealer
                if s.dealer_id not in seen:
                    seen.add(s.dealer_id)
                    n, total = score.get(s.dealer_id, (0, Decimal(0)))
                    score[s.dealer_id] = (n + 1, total + s.price)
    if score:
        best = max(score, key=lambda d: (score[d][0], -score[d][1]))
        kit.dealer = dealers[best]
    pickups = await stocks.pickup_dealers(user.region_id)
    pickup = kit.dealer if can_pickup(kit.dealer) else (pickups[0] if pickups else None)
    for kind in kinds:
        line = KitLine(kind=kind, qty=QUANTITY.get(kind, 1))
        options = offers[kind]
        at_dealer = [(p, s) for p, local in options for s in local if kit.dealer and s.dealer_id == kit.dealer.id]
        elsewhere = [(p, s) for p, local in options for s in local]
        pick = (at_dealer or elsewhere or [None])[0]
        if pick is None and pickup is not None:  # в регионе нет — предзаказ со склада JAC
            for part, _ in options:
                stock = await stocks.warehouse_offer(part.id)
                if stock is not None and stock.quantity >= line.qty:
                    pick, line.pickup = (part, stock), pickup
                    break
        if pick is not None:
            line.part, line.stock = pick
        elif options:
            line.part = options[0][0]  # деталь есть в каталоге, но не в наличии — покажем номер
        kit.lines.append(line)
    return kit


async def add_kit_to_cart(session: AsyncSession, user: User, kit: Kit) -> tuple[list[KitLine], list[KitLine]]:
    """Положить набор в корзину (по нужному числу штук). → (добавлено, не получилось)."""
    cart = CartRepository(session)
    in_cart = {item.stock_id: item.quantity for item in await cart.items(user)}  # уже лежит — не удваиваем
    added, failed = [], []
    for line in kit.found:
        have = in_cart.get(line.stock.id, 0)
        while have < line.qty:
            ok, have = await cart.add(user, line.stock, line.pickup)
            if not ok:
                break
        (added if have >= line.qty else failed).append(line)
    return added, failed
