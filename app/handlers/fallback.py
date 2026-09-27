"""Подключается последним: ловит устаревшие или подделанные кнопки,
чтобы в Telegram не «крутились часики» бесконечно."""
from aiogram import Router
from aiogram.types import CallbackQuery

from app.database.models import User
from app.services.localization import i18n

router = Router(name="fallback")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery, user: User) -> None:
    await callback.answer(i18n.t(user.language, "item_unavailable"), show_alert=True)
