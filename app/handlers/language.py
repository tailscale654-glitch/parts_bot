from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SUPPORTED_LANGUAGES, User
from app.database.repositories.users import UserRepository
from app.handlers.start import main_menu_text
from app.keyboards.language import language_keyboard
from app.keyboards.main import main_menu_keyboard
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
    await callback.answer(i18n.t(code, "language_saved"))
    await callback.message.edit_text(main_menu_text(user), reply_markup=main_menu_keyboard(code))
