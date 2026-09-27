"""Профиль: телефон, регион, язык."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.database.models import User
from app.handlers.start import profile_view
from app.keyboards.phone import phone_keyboard
from app.services.localization import i18n

router = Router(name="profile")


@router.callback_query(F.data == "profile:show")
async def show_profile(callback: CallbackQuery, user: User) -> None:
    text, kb = profile_view(user)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "profile:phone")
async def change_phone(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await callback.message.answer(
        i18n.t(user.language, "ask_phone_change"), reply_markup=phone_keyboard(user.language, with_cancel=True)
    )
