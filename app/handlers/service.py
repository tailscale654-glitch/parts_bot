"""ТО и пробег в чате: «🔧 ТО и пробег» в профиле, вопрос о пробеге раз в месяц, напоминание о ТО
и «🛒 Набор для ТО-N» — расходники для модели клиента сразу в корзину у дилера его региона.

Пробег отвечают числом в чат («23400», «23 400 км») или кнопкой с примерным значением (по прошлым ответам).
Число считаем пробегом, только если бот недавно спросил (3 дня) и клиент ещё не ответил.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.services import cars
from app.services import maintenance as m
from app.services.catalog import money
from app.services.localization import i18n

router = Router(name="service")


class ServiceCB(CallbackData, prefix="to"):
    action: str  # show | ask | km | later | kit
    n: int = 0


def km(value: int, lang: str | None) -> str:
    """23400 → «23 400 км»."""
    return f"{value:,}".replace(",", " ") + f" {i18n.t(lang, 'km_unit')}"


def items_text(user: User, number: int) -> str:
    return "\n".join(f"• {i18n.t(user.language, f'kit_{k}')}" for k in m.kinds_for(user.car_model, number))


def car_title(user: User) -> str:
    return cars.car_text(user, user.language) or user.car_model or ""


def _kb(*rows: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in rows])


def kit_button(user: User, number: int) -> tuple[str, str]:
    return i18n.t(user.language, "btn_kit", number=number), ServiceCB(action="kit", n=number).pack()


def mileage_button(user: User) -> tuple[str, str]:
    return i18n.t(user.language, "btn_mileage"), ServiceCB(action="ask").pack()


def service_view(user: User) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    if not user.car_model:
        from app.keyboards.car import CarCB

        return i18n.t(lang, "service_no_car"), _kb((i18n.t(lang, "btn_change_car"), CarCB(action="start").pack()))
    if user.car_mileage is None:
        return i18n.t(lang, "service_no_mileage", car=car_title(user)), _kb(mileage_button(user))
    due = m.next_service(user.car_model, user.car_mileage)
    from app.services.orders import fmt_date

    text = i18n.t(lang, "service_status", car=car_title(user), km=km(user.car_mileage, lang),
                  date=fmt_date(user.car_mileage_at)[:10], number=due.number, at=km(due.km, lang),
                  left=km(due.left, lang), items=items_text(user, due.number))
    return text, _kb(kit_button(user, due.number), mileage_button(user))


async def mileage_question(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup]:
    """«Какой сейчас пробег?» + кнопки с примерным пробегом (если есть история) и «Не сейчас».
    Отмечаем, что спросили: следующее число в чате будет пробегом."""
    lang = user.language
    guess = await m.estimate(session, user)
    rows = []
    if guess:
        rows += [(i18n.t(lang, "btn_km", km=km(v, lang)), ServiceCB(action="km", n=v).pack())
                 for v in (guess - 1000, guess, guess + 1000) if v > (user.car_mileage or 0)]
    rows.append((i18n.t(lang, "btn_later"), ServiceCB(action="later").pack()))
    user.mileage_asked_at = datetime.now(timezone.utc)
    await session.commit()
    hint = i18n.t(lang, "mileage_hint") if guess else ""
    return i18n.t(lang, "mileage_ask", car=car_title(user), hint=hint), _kb(*rows)


async def mileage_reply(session: AsyncSession, user: User, value: int) -> tuple[str, InlineKeyboardMarkup]:
    """Пробег сохранили: пора ТО — напоминание с набором; нет — когда следующее."""
    lang = user.language
    await m.save_mileage(session, user, value)
    due = m.due_reminder(user)
    if due is not None:
        user.service_reminded_km = due.km
        await session.commit()
        return reminder_text(user, due), _kb(kit_button(user, due.number))
    nxt = m.next_service(user.car_model, value)
    return (i18n.t(lang, "mileage_saved", km=km(value, lang), number=nxt.number, at=km(nxt.km, lang),
                   left=km(nxt.left, lang)), _kb(kit_button(user, nxt.number)))


def reminder_text(user: User, due: m.Due) -> str:
    lang = user.language
    key = "service_reminder" if due.left > 0 else "service_reminder_due"
    return i18n.t(lang, key, car=car_title(user), number=due.number, km=km(user.car_mileage, lang),
                  at=km(due.km, lang), left=km(max(due.left, 0), lang), items=items_text(user, due.number))


# ---------- кнопки и ответы ----------

@router.callback_query(ServiceCB.filter(F.action == "show"))
async def show(callback: CallbackQuery, user: User) -> None:
    text, kb = service_view(user)
    await callback.answer()
    await callback.message.answer(text, reply_markup=kb)


@router.callback_query(ServiceCB.filter(F.action == "ask"))
async def ask(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    text, kb = await mileage_question(session, user)
    await callback.answer()
    await callback.message.answer(text, reply_markup=kb)


@router.callback_query(ServiceCB.filter(F.action == "km"))
async def pick_km(callback: CallbackQuery, callback_data: ServiceCB, user: User, session: AsyncSession) -> None:
    if not user.car_model or not 0 < callback_data.n < 2_000_000:  # данным из кнопки не доверяем
        await callback.answer()
        return
    text, kb = await mileage_reply(session, user, callback_data.n)
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(ServiceCB.filter(F.action == "later"))
async def later(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    # «спросили 3 дня назад»: число в чате уже не ловим, а следующий вопрос — примерно через месяц
    user.mileage_asked_at = datetime.now(timezone.utc) - timedelta(days=3, seconds=1)
    await session.commit()
    await callback.answer()
    await callback.message.edit_text(i18n.t(user.language, "mileage_later"))


async def mileage_wanted(message: Message, user: User | None = None) -> bool:
    return user is not None and bool(user.car_model) and m.asked_recently(user)


@router.message(StateFilter(None), F.text.func(lambda t: m.parse_mileage(t) is not None), mileage_wanted)
async def typed_km(message: Message, user: User, session: AsyncSession) -> None:
    text, kb = await mileage_reply(session, user, m.parse_mileage(message.text))
    await message.answer(text, reply_markup=kb)


@router.callback_query(ServiceCB.filter(F.action == "kit"))
async def kit(callback: CallbackQuery, callback_data: ServiceCB, user: User, session: AsyncSession) -> None:
    from app.handlers.cart import cart_view

    lang = user.language
    if not user.car_model or not 1 <= callback_data.n <= 200:
        await callback.answer()
        return
    await callback.answer()
    built = await m.build_kit(session, user, callback_data.n)
    added, failed = await m.add_kit_to_cart(session, user, built)
    if not added:
        await callback.message.answer(i18n.t(lang, "kit_empty", number=built.number))
        return
    lines = []
    for line in added:
        where = i18n.t(lang, "kit_preorder") if line.stock.dealer.is_warehouse else ""
        if not line.stock.dealer.is_warehouse and built.dealer and line.stock.dealer_id != built.dealer.id:
            where = f" ({line.stock.dealer.name})"  # не у основного дилера набора — пишем, у кого
        qty = f" × {line.qty}" if line.qty > 1 else ""
        lines.append(i18n.t(lang, "kit_line", name=i18n.t(lang, f"kit_{line.kind}"), qty=qty,
                            number=line.part.part_number, price=money(line.price, lang), where=where))
    missing = [i18n.t(lang, f"kit_{line.kind}") for line in (*built.missing, *failed)]
    total = sum((line.price for line in added), Decimal(0))
    dealer = built.dealer.name if built.dealer else ""
    text = i18n.t(lang, "kit_added", number=built.number, lines="\n".join(lines), total=money(total, lang),
                  dealer=i18n.t(lang, "kit_dealer", dealer=dealer) if dealer else "",
                  missing=i18n.t(lang, "kit_missing", names=", ".join(missing)) if missing else "")
    await callback.message.answer(text)
    cart_text, cart_kb = await cart_view(user, session)
    await callback.message.answer(cart_text, reply_markup=cart_kb)


# ---------- раз в месяц: спросить пробег ----------

async def ask_mileage_round(bot: Bot, session: AsyncSession, now: datetime | None = None, limit: int = 40) -> int:
    """Фоновая задача (раз в полчаса, днём по Ташкенту): у кого есть машина и пробег не спрашивали месяц —
    спросить. Не больше `limit` сообщений за раз."""
    from app.services.notify import send
    from app.services.orders import TIMEZONE

    now = now or datetime.now(timezone.utc)
    if not 10 <= now.astimezone(TIMEZONE).hour < 20:  # не будим ночью
        return 0
    month = now - timedelta(days=m.ASK_EVERY_DAYS)
    users = (await session.scalars(select(User).where(
        User.car_model.is_not(None), User.phone.is_not(None), User.blocked.is_(False),
        User.created_at < now - timedelta(days=1),
        or_(User.mileage_asked_at.is_(None), User.mileage_asked_at < month),
        or_(User.car_mileage_at.is_(None), User.car_mileage_at < month)).limit(limit))).unique().all()
    for user in users:
        text, kb = await mileage_question(session, user)  # заодно отмечает «спросили»
        await send(bot, user.telegram_id, text, kb)
    return len(users)
