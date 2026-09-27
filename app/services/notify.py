"""Уведомления: администраторам — о новом заказе, клиенту — о смене статуса."""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import Order, User
from app.keyboards.orders import admin_order_keyboard
from app.services.localization import i18n
from app.services.orders import order_text, status_text

logger = logging.getLogger(__name__)


async def _admin_languages(session: AsyncSession, admin_ids: set[int]) -> dict[int, str | None]:
    """Язык каждого админа — из его профиля в боте, иначе русский."""
    rows = await session.execute(select(User.telegram_id, User.language).where(User.telegram_id.in_(admin_ids)))
    langs = dict(rows.all())
    return {admin_id: langs.get(admin_id) for admin_id in admin_ids}


async def notify_admins_new_order(bot: Bot, settings: Settings, session: AsyncSession, order: Order) -> None:
    for admin_id, lang in (await _admin_languages(session, settings.admin_ids)).items():
        try:
            await bot.send_message(admin_id, order_text(order, lang, for_admin=True),
                                   reply_markup=admin_order_keyboard(order, lang))
        except TelegramAPIError as e:  # админ не запускал бота или заблокировал его
            logger.warning("Cannot notify admin %s about order %s: %s", admin_id, order.id, e)


async def notify_admins_text(bot: Bot, settings: Settings, session: AsyncSession, key: str, **params) -> None:
    for admin_id, lang in (await _admin_languages(session, settings.admin_ids)).items():
        try:
            await bot.send_message(admin_id, i18n.t(lang, key, **params))
        except TelegramAPIError as e:
            logger.warning("Cannot notify admin %s: %s", admin_id, e)


async def notify_client_status(bot: Bot, order: Order) -> None:
    user = order.user
    try:
        await bot.send_message(
            user.telegram_id,
            i18n.t(user.language, "order_status_changed", id=order.id, status=status_text(order.status, user.language)),
        )
    except TelegramAPIError as e:
        logger.warning("Cannot notify client %s about order %s: %s", user.telegram_id, order.id, e)
