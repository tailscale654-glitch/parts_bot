"""/start, регистрация по шагам и постоянное меню внизу экрана."""
from aiogram import F, Router
from aiogram import Bot
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.config import Settings
from app.database.repositories.regions import RegionRepository
from app.database.repositories.staff import InviteError, StaffRepository
from app.handlers.cart import cart_view
from app.handlers.catalog import car_prompt, full_access, models_view
from app.handlers.orders import orders_view
from app.keyboards.language import language_keyboard
from app.keyboards.main import main_reply_keyboard, menu_action, profile_keyboard
from app.keyboards.phone import phone_keyboard
from app.keyboards.region import region_keyboard
from app.services import bot_settings, cars
from app.services.bot_settings import contact_view
from app.services.localization import i18n, localized_name
from app.states.search import SearchStates

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
    vin = f"\n{i18n.t(lang, 'vin_line', vin=user.car_vin)}" if user.car_vin else ""
    if user.car_engine:
        vin += f"\n{i18n.t(lang, 'engine_line', engine=user.car_engine)}"
    if user.car_mileage is not None:
        from app.handlers.service import km

        vin += f"\n{i18n.t(lang, 'mileage_line', km=km(user.car_mileage, lang))}"
    return f"{text}\n{cars.car_line(user, lang)}{vin}", profile_keyboard(lang)


async def region_prompt(user: User, session: AsyncSession, with_back: bool = False):
    """Текст и клавиатура выбора региона (регионы берутся из PostgreSQL)."""
    regions = await RegionRepository(session).list_active()
    return i18n.t(user.language, "choose_region"), region_keyboard(regions, user.language, with_back)


async def send_main_menu(message: Message, user: User, session: AsyncSession, prefix: str | None = None) -> None:
    text = f"{prefix}\n\n{main_menu_text(user)}" if prefix else main_menu_text(user)
    staff = await StaffRepository(session).dealer_id_for(user) is not None  # у сотрудника дилера — своя кнопка
    await message.answer(text, reply_markup=main_reply_keyboard(user.language, staff=staff))


async def needs_car(user: User, session: AsyncSession) -> bool:
    """Автомобиль спрашиваем у клиентов; сотрудникам дилеров он не нужен."""
    return cars.needs_car(user) and await StaffRepository(session).dealer_id_for(user) is None


async def next_step(message: Message, user: User, session: AsyncSession) -> None:
    """Регистрация по шагам: язык → регион → телефон → VIN (машина из CarSale) или модель вручную → главное меню.
    Телефон раньше VIN: витрина со сканером открывается только зарегистрированным (с телефоном)."""
    if user.language is None:
        await message.answer(i18n.t(None, "choose_language"), reply_markup=language_keyboard())
    elif user.region_id is None:
        text, kb = await region_prompt(user, session)
        await message.answer(text, reply_markup=kb)
    elif not user.phone:
        await message.answer(i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language))
    elif await needs_car(user, session):
        text, kb = car_prompt(user)
        await message.answer(text, reply_markup=kb)
    else:
        await send_main_menu(message, user, session)


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^dealer_[\w-]+$")))
async def start_invite(
    message: Message, command: CommandObject, user: User, session: AsyncSession, bot: Bot, settings: Settings,
) -> None:
    """Ссылка-приглашение t.me/бот?start=dealer_XXXX → пользователь становится сотрудником дилера."""
    from app.services.notify import notify_admins_text, person_name

    try:
        dealer = await StaffRepository(session).accept_invite(command.args.removeprefix("dealer_"), user)
    except InviteError as e:
        await message.answer(i18n.t(user.language, f"invite_{e.reason}"))
    else:
        await message.answer(i18n.t(user.language, "invite_ok", dealer=dealer.name))
        await notify_admins_text(bot, settings, session, "admin_staff_joined", name=person_name(user), dealer=dealer.name)
    await next_step(message, user, session)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, session: AsyncSession, state: FSMContext | None = None) -> None:
    await leave_search(state)
    await next_step(message, user, session)


async def leave_search(state: FSMContext | None) -> None:
    """Нажали другую кнопку меню — выходим из режима поиска или ввода VIN (последний запрос остаётся в данных)."""
    from app.handlers.vin import VinStates

    if state is not None and await state.get_state() in (SearchStates.query.state, VinStates.wait.state):
        await state.set_state(None)


@router.message(F.text.func(menu_action))
async def menu_button(message: Message, user: User, session: AsyncSession, staff_dealer_id: int | None,
                      settings: Settings | None = None, state: FSMContext | None = None) -> None:
    """Нажата кнопка нижнего меню (на любом языке)."""
    await leave_search(state)
    if not (user.language and user.region_id and user.phone):
        await next_step(message, user, session)  # регистрация не закончена
        return
    lang = user.language
    action = menu_action(message.text)
    if action == "btn_search":
        from app.handlers.search import start_search

        if cars.needs_car(user) and staff_dealer_id is None:  # ищем по автомобилю клиента — сначала спросим его
            text, kb = car_prompt(user)
            await message.answer(text, reply_markup=kb)
        elif state is not None:
            await start_search(message, user, state, full_access(user, settings, staff_dealer_id))
    elif action == "btn_catalog":
        text, kb = await models_view(user, session, full_access(user, settings, staff_dealer_id))
        await message.answer(text, reply_markup=kb)
    elif action == "btn_cart":
        text, kb = await cart_view(user, session)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_my_orders":
        text, kb = await orders_view(user, session)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_profile":
        text, kb = profile_view(user)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_manager":  # контакты задаются в веб-панели: ⚙️ Настройки
        text, kb = contact_view(await bot_settings.load(session), lang)
        await message.answer(text, reply_markup=kb)
    elif action == "btn_cancel":
        await send_main_menu(message, user, session, prefix=i18n.t(lang, "cancelled"))
    elif action == "btn_dealer_orders":
        if staff_dealer_id is None:
            await message.answer(i18n.t(lang, "not_staff"))
            return
        from app.handlers.dealer import dealer_orders_view

        text, kb = await dealer_orders_view(session, staff_dealer_id, lang)
        await message.answer(text, reply_markup=kb)


# --- Кнопки из старых сообщений (до нижнего меню), чтобы они не «ломались» ---

@router.callback_query(F.data.in_({"menu:home", "menu:orders", "menu:contact"}))
async def legacy_menu(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    await callback.answer()
    await send_main_menu(callback.message, user, session)
