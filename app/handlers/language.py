from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SUPPORTED_LANGUAGES, User
from app.database.repositories.users import UserRepository
from app.handlers.start import next_step, region_prompt
from app.keyboards.language import language_keyboard
from app.services.localization import i18n

router = Router(name="language")


@router.callback_query(F.data == "menu:language")
async def ask_language(callback: CallbackQuery) -> None:
    await callback.message.edit_text(i18n.t(None, "choose_language"), reply_markup=language_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    code = callback.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGUAGES:  # не доверяем данным из Telegram
        await callback.answer()
        return
    await UserRepository(session).set_language(user, code)
    await callback.answer()
    if user.region_id is None:
        # Первый запуск: после языка сразу просим выбрать регион
        text, kb = await region_prompt(user, session)
        await callback.message.edit_text(text, reply_markup=kb)
        return
    await callback.message.edit_text(i18n.t(code, "language_saved"))
    # Новое сообщение — чтобы нижнее меню тоже сменило язык
    await next_step(callback.message, user, session)
