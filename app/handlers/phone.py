"""Номер телефона: при регистрации (после региона) и при смене из профиля."""
from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.users import UserRepository
from app.handlers.catalog import models_view
from app.handlers.start import next_step, send_main_menu
from app.keyboards.main import main_reply_keyboard
from app.keyboards.phone import phone_keyboard
from app.services.localization import i18n
from app.utils.validators import normalize_phone

router = Router(name="phone")


async def ask_phone(message: Message, user: User) -> None:
    await message.answer(i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language))


async def open_catalog(message: Message, user: User, session: AsyncSession) -> None:
    text, kb = await models_view(user, session)
    await message.answer(text, reply_markup=kb)


@router.message(F.contact)
async def got_contact(message: Message, user: User, session: AsyncSession) -> None:
    lang = user.language
    # Принимаем только собственный номер, а не пересланный чужой контакт
    if message.contact.user_id != message.from_user.id:
        await message.answer(i18n.t(lang, "phone_not_own"), reply_markup=phone_keyboard(lang))
        return
    phone = normalize_phone(message.contact.phone_number)
    if phone is None:
        await message.answer(i18n.t(lang, "phone_invalid"), reply_markup=phone_keyboard(lang))
        return
    first_time = not user.phone
    await UserRepository(session).set_phone(user, phone)
    saved = i18n.t(lang, "phone_saved", phone=phone)
    if first_time:
        # Конец регистрации: показываем нижнее меню и сразу открываем каталог
        await message.answer(saved, reply_markup=main_reply_keyboard(lang))
        await open_catalog(message, user, session)
    else:
        await send_main_menu(message, user, prefix=saved)


@router.message()
async def other_message(message: Message, user: User, session: AsyncSession) -> None:
    """Любое другое сообщение: подсказываем следующий шаг (или показываем меню)."""
    await next_step(message, user, session)
