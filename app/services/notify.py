"""Уведомления: о новом заказе — администраторам и сотрудникам дилера;
о смене статуса — клиенту и всем остальным участникам (кроме того, кто изменил)."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import Order, User
from app.database.repositories.staff import StaffRepository
from app.keyboards.orders import admin_order_keyboard
from app.services.localization import i18n
from app.services.orders import order_text, status_text

logger = logging.getLogger(__name__)


def person_name(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or (f"@{user.username}" if user.username else "—")


async def send(bot: Bot, chat_id: int, text: str, kb: InlineKeyboardMarkup | None = None) -> bool:
    """Отправить, не падая, если человек не запускал бота или заблокировал его."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, text, reply_markup=kb)
            return True
        except TelegramRetryAfter as e:  # Telegram просит подождать (много сообщений подряд)
            if attempt:
                logger.warning("Rate limited sending to %s", chat_id)
                return False
            await asyncio.sleep(min(e.retry_after, 30))
        except TelegramAPIError as e:
            logger.warning("Cannot send message to %s: %s", chat_id, e)
            return False
    return False


async def admin_recipients(session: AsyncSession, settings: Settings) -> list[tuple[int, str | None]]:
    """(telegram_id, язык) администраторов. Язык — из профиля в боте, иначе русский."""
    rows = await session.execute(select(User.telegram_id, User.language).where(User.telegram_id.in_(settings.admin_ids)))
    langs = dict(rows.all())
    return [(admin_id, langs.get(admin_id)) for admin_id in sorted(settings.admin_ids)]


async def staff_recipients(session: AsyncSession, dealer_id: int) -> list[tuple[int, str | None]]:
    return [(s.user.telegram_id, s.user.language) for s in await StaffRepository(session).staff_of(dealer_id)]


async def notify_new_order(bot: Bot, settings: Settings, session: AsyncSession, order: Order) -> None:
    admins = await admin_recipients(session, settings)
    admin_ids = {a for a, _ in admins}
    for chat_id, lang in admins:
        await send(bot, chat_id, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang))
    for chat_id, lang in await staff_recipients(session, order.dealer_id):
        if chat_id not in admin_ids:  # если админ сам сотрудник дилера — одного сообщения достаточно
            await send(bot, chat_id, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang, staff=True))


def actor_text(actor: User, role: str, lang: str | None, dealer_name: str) -> str:
    return i18n.t(lang, f"role_{role}", name=person_name(actor), dealer=dealer_name)


async def notify_status_change(
    bot: Bot, settings: Settings, session: AsyncSession, order: Order, actor: User, role: str,
) -> None:
    """role: admin | staff | client. Клиенту — всегда (если менял не он), остальным — коротко, кто что сделал."""
    client = order.user
    if actor.id != client.id:
        await send(bot, client.telegram_id, i18n.t(
            client.language, "order_status_changed", id=order.id, status=status_text(order.status, client.language)))
    recipients = dict(await admin_recipients(session, settings))
    for chat_id, lang in await staff_recipients(session, order.dealer_id):
        recipients.setdefault(chat_id, lang)
    recipients.pop(actor.telegram_id, None)
    for chat_id, lang in recipients.items():
        await send(bot, chat_id, i18n.t(
            lang, "status_changed_by", id=order.id, status=status_text(order.status, lang),
            who=actor_text(actor, role, lang, order.dealer.name)))


async def notify_admins_text(bot: Bot, settings: Settings, session: AsyncSession, key: str, **params) -> None:
    for chat_id, lang in await admin_recipients(session, settings):
        await send(bot, chat_id, i18n.t(lang, key, **params))
