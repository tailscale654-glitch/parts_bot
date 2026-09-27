from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.database.models import User
from app.keyboards.language import language_keyboard
from app.keyboards.main import back_to_menu_keyboard, main_menu_keyboard
from app.services.localization import i18n

router = Router(name="start")


def main_menu_text(user: User) -> str:
    lang = user.language
    region = i18n.t(lang, "region_not_selected")  # регионы появятся на этапе 2
    return f"{i18n.t(lang, 'main_menu_title')}\n\n{i18n.t(lang, 'region_line', region=region)}"


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    if user.language is None:
        await message.answer(i18n.t(None, "choose_language"), reply_markup=language_keyboard())
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


@router.callback_query(F.data.in_({"menu:catalog", "menu:orders", "menu:region"}))
async def coming_soon(callback: CallbackQuery, user: User) -> None:
    # Заглушки: каталог, заказы и регионы делаем на следующих этапах
    await callback.answer(i18n.t(user.language, "coming_soon"), show_alert=True)
