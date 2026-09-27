from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.regions import RegionRepository
from app.keyboards.language import language_keyboard
from app.keyboards.main import back_to_menu_keyboard, main_menu_keyboard
from app.keyboards.region import region_keyboard
from app.services.localization import i18n, localized_name

router = Router(name="start")


def main_menu_text(user: User) -> str:
    lang = user.language
    region = localized_name(user.region, lang) if user.region else i18n.t(lang, "region_not_selected")
    return f"{i18n.t(lang, 'main_menu_title')}\n\n{i18n.t(lang, 'region_line', region=region)}"


async def region_prompt(user: User, session: AsyncSession, with_back: bool = False):
    """Текст и клавиатура выбора региона (регионы берутся из PostgreSQL)."""
    regions = await RegionRepository(session).list_active()
    return i18n.t(user.language, "choose_region"), region_keyboard(regions, user.language, with_back)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, session: AsyncSession) -> None:
    if user.language is None:
        await message.answer(i18n.t(None, "choose_language"), reply_markup=language_keyboard())
        return
    if user.region_id is None:
        text, kb = await region_prompt(user, session)
        await message.answer(text, reply_markup=kb)
        return
    await message.answer(main_menu_text(user), reply_markup=main_menu_keyboard(user.language))


@router.callback_query(F.data == "menu:home")
async def show_main_menu(callback: CallbackQuery, user: User) -> None:
    await callback.message.edit_text(main_menu_text(user), reply_markup=main_menu_keyboard(user.language))
    await callback.answer()


@router.callback_query(F.data == "menu:contact")
async def contact_manager(callback: CallbackQuery, user: User) -> None:
    await callback.message.edit_text(
        i18n.t(user.language, "contact_manager_text"), reply_markup=back_to_menu_keyboard(user.language)
    )
    await callback.answer()


@router.callback_query(F.data == "menu:orders")
async def coming_soon(callback: CallbackQuery, user: User) -> None:
    # Заглушка: заказы делаем на этапе 6
    await callback.answer(i18n.t(user.language, "coming_soon"), show_alert=True)
