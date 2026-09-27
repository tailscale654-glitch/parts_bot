"""/start, регистрация по шагам и постоянное меню внизу экрана."""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.regions import RegionRepository
from app.handlers.catalog import models_view
from app.keyboards.language import language_keyboard
from app.keyboards.main import main_reply_keyboard, menu_action, profile_keyboard
from app.keyboards.phone import phone_keyboard
from app.keyboards.region import region_keyboard
from app.services.localization import i18n, localized_name

router = Router(name="start")


def region_title(user: User) -> str:
    return localized_name(user.region, user.language) if user.region else i18n.t(user.language, "region_not_selected")


def main_menu_text(user: User) -> str:
    lang = user.language
    return (
        f"{i18n.t(lang, 'main_menu_title')}\n\n"
        f"{i18n.t(lang, 'region_line', region=region_title(user))}\n\n"
        f"{i18n.t(lang, 'menu_hint')}"
    )


def profile_view(user: User) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
    text = i18n.t(
        lang, "profile_text",
        name=name, phone=user.phone or "—", region=region_title(user), language=i18n.t(lang, "language_name"),
    )
    return text, profile_keyboard(lang)


async def region_prompt(user: User, session: AsyncSession, with_back: bool = False):
    """Текст и клавиатура выбора региона (регионы берутся из PostgreSQL)."""
    regions = await RegionRepository(session).list_active()
    return i18n.t(user.language, "choose_region"), region_keyboard(regions, user.language, with_back)


async def send_main_menu(message: Message, user: User, prefix: str | None = None) -> None:
    text = f"{prefix}\n\n{main_menu_text(user)}" if prefix else main_menu_text(user)
    await message.answer(text, reply_markup=main_reply_keyboard(user.language))


async def next_step(message: Message, user: User, session: AsyncSession) -> None:
    """Регистрация по шагам: язык → регион → телефон → главное меню."""
    if user.language is None:
        await message.answer(i18n.t(None, "choose_language"), reply_markup=language_keyboard())
    elif user.region_id is None:
        text, kb = await region_prompt(user, session)
        await message.answer(text, reply_markup=kb)
    elif not user.phone:
        await message.answer(i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language))
    else:
        await send_main_menu(message, user)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, session: AsyncSession) -> None:
    await next_step(message, user, session)


@router.message(F.text.func(menu_action))
async def menu_button(message: Message, user: User, session: AsyncSession) -> None:
    """Нажата кнопка нижнего меню (на любом языке)."""
    if not (user.language and user.region_id and user.phone):
        await next_step(message, user, session)  # регистрация не закончена
        return
    lang = user.language
    action = menu_action(message.text)
    if action == "btn_catalog":
        text, kb = await models_view(user, session)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_cart":
        await message.answer(i18n.t(lang, "cart_empty"))
    elif action == "btn_my_orders":
        await message.answer(i18n.t(lang, "orders_empty"))
    elif action == "btn_profile":
        text, kb = profile_view(user)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_manager":
        await message.answer(i18n.t(lang, "contact_manager_text"))
    elif action == "btn_cancel":
        await send_main_menu(message, user, prefix=i18n.t(lang, "cancelled"))


# --- Кнопки из старых сообщений (до нижнего меню), чтобы они не «ломались» ---

@router.callback_query(F.data.in_({"menu:home", "menu:orders", "menu:contact"}))
async def legacy_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await send_main_menu(callback.message, user)
