"""VIN автомобиля при регистрации (после телефона) и из профиля.

Клиент сканирует VIN в витрине (кнопка «📷 Сканировать VIN»), присылает фото номера или пишет его сообщением.
Бот ищет машину среди проданных JAC Motors Toshkent (CarSale CRM, «Остатки» → «Архив») и показывает
карточку: модель, комплектация, цвет, номер двигателя. «Да, это моя» — всё сохраняется в профиль.
Не нашли (или CRM недоступна) — модель выбирают вручную, VIN всё равно сохраняется.
"""
import asyncio
import io

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.users import UserRepository
from app.keyboards.car import CarCB
from app.services import cars
from app.services.localization import i18n
from app.services.vin import MAX_UPLOAD, is_valid, normalize, read_vin
from app.services.vin_car import FOUND, MISSING, apply, card_lines, lookup

router = Router(name="vin")


class VinStates(StatesGroup):
    wait = State()  # попросили VIN («Изменить автомобиль», «Другой VIN») — следующий текст или фото читаем как VIN


class VinCB(CallbackData, prefix="vin"):
    action: str  # ok | again
    vin: str = ""


def scan_url() -> str | None:
    """Витрина сразу со сканером (?start=vin). Без MINIAPP_URL кнопки нет — остаются фото и текст."""
    from app.config import miniapp_url

    url = miniapp_url()
    return f"{url}{'&' if '?' in url else '?'}start=vin" if url else None


def vin_prompt(user: User) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    rows = []
    url = scan_url()
    if url:
        rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_scan_vin"), web_app=WebAppInfo(url=url))])
    rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_car_manual"), callback_data=CarCB(action="manual").pack())])
    return i18n.t(lang, "vin_prompt"), InlineKeyboardMarkup(inline_keyboard=rows)


async def ask_vin(message: Message, user: User, state: FSMContext | None = None) -> None:
    text, kb = vin_prompt(user)
    if state is not None:
        await state.set_state(VinStates.wait)
    await message.answer(text, reply_markup=kb)


async def vin_wanted(message: Message, user: User | None = None, state: FSMContext | None = None) -> bool:
    """VIN ждём у клиента без автомобиля (регистрация) или когда его попросили (состояние wait)."""
    if user is None or not (user.language and user.region_id and user.phone):
        return False
    if state is not None and await state.get_state() == VinStates.wait.state:
        return True
    return cars.needs_car(user) and (await state.get_state() if state is not None else None) is None


def looks_like_vin(text: str | None) -> bool:
    return is_valid(normalize(text))


@router.message(F.text.func(looks_like_vin), vin_wanted)
async def vin_text(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    await check_vin(message, user, session, state, normalize(message.text))


@router.message(F.photo | F.document.mime_type.startswith("image/"), vin_wanted)
async def vin_photo(message: Message, user: User, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    lang = user.language
    file = message.photo[-1] if message.photo else message.document
    if (file.file_size or 0) > MAX_UPLOAD:
        await message.answer(i18n.t(lang, "vin_photo_failed"))
        return
    wait = await message.answer(i18n.t(lang, "vin_reading_photo"))
    buffer = io.BytesIO()
    await bot.download(file, destination=buffer)
    vin, _ = await asyncio.to_thread(read_vin, buffer.getvalue())  # фото не сохраняем — только читаем номер
    if not vin:
        await wait.edit_text(i18n.t(lang, "vin_photo_failed"))
        return
    await wait.delete()
    await check_vin(message, user, session, state, vin)


@router.message(VinStates.wait, F.text, ~F.text.startswith("/"))
async def vin_bad_text(message: Message, user: User) -> None:
    """Попросили VIN, а прислали что-то другое (кнопки меню сюда не попадают — их ловит start раньше)."""
    await message.answer(i18n.t(user.language, "vin_bad_text"))


async def check_vin(message: Message, user: User, session: AsyncSession, state: FSMContext, vin: str) -> None:
    lang = user.language
    wait = await message.answer(i18n.t(lang, "vin_checking", vin=vin))
    status, sold = await lookup(vin)
    if status == FOUND:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=i18n.t(lang, "btn_vin_yes"), callback_data=VinCB(action="ok", vin=vin).pack())],
            [InlineKeyboardButton(text=i18n.t(lang, "btn_vin_other"), callback_data=VinCB(action="again").pack())]])
        await wait.edit_text(i18n.t(lang, "vin_found", card="\n".join(card_lines(sold, lang))), reply_markup=kb)
        return
    # не нашли или CRM недоступна: VIN запомним — сохраним после ручного выбора модели
    await state.update_data(pending_vin=vin)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "btn_car_manual"), callback_data=CarCB(action="manual").pack())],
        [InlineKeyboardButton(text=i18n.t(lang, "btn_vin_other"), callback_data=VinCB(action="again").pack())]])
    await wait.edit_text(i18n.t(lang, "vin_missing" if status == MISSING else "vin_unavailable", vin=vin), reply_markup=kb)


@router.callback_query(VinCB.filter(F.action == "ok"))
async def vin_confirm(callback: CallbackQuery, callback_data: VinCB, user: User, session: AsyncSession,
                      state: FSMContext) -> None:
    lang = user.language
    vin = normalize(callback_data.vin)
    status, sold = await lookup(vin) if is_valid(vin) else (MISSING, None)  # данным из кнопки не доверяем
    if status != FOUND:
        await callback.answer(i18n.t(lang, "vin_recheck_failed"), show_alert=True)
        return
    first_time = cars.needs_car(user)
    await apply(session, user, vin, sold)
    await state.set_state(None)
    await state.update_data(pending_vin=None)
    await callback.answer()
    await callback.message.edit_text(i18n.t(lang, "vin_saved", card="\n".join(card_lines(sold, lang))))
    await after_car_saved(callback.message, user, session, first_time)


@router.callback_query(VinCB.filter(F.action == "again"))
async def vin_again(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    await ask_vin(callback.message, user, state)


async def after_car_saved(message: Message, user: User, session: AsyncSession, first_time: bool) -> None:
    """Машина сохранена: модели нет в боте — просим выбрать вручную; иначе сразу каталог."""
    from app.handlers.catalog import models_view
    from app.keyboards.car import models_keyboard

    lang = user.language
    if not user.car_model:
        await message.answer(i18n.t(lang, "choose_car_model"), reply_markup=models_keyboard())
        return
    if user.car_color is None:  # цвета из CarSale нет в боте — один вопрос
        from app.keyboards.car import colors_keyboard

        await message.answer(i18n.t(lang, "choose_car_color", model=cars.car_text(user, lang)),
                             reply_markup=colors_keyboard(user.car_model, user.car_modification, lang))
        return
    text, kb = await models_view(user, session)
    await message.answer(text, reply_markup=kb)


async def save_pending_vin(user: User, session: AsyncSession, state: FSMContext | None) -> None:
    """После ручного выбора модели: VIN, который не нашёлся в CarSale, всё равно сохраняем в профиль."""
    if state is None:
        return
    vin = (await state.get_data()).get("pending_vin")
    if vin and is_valid(vin):
        await UserRepository(session).set_car(user, vin=vin)
    await state.update_data(pending_vin=None)
    if await state.get_state() == VinStates.wait.state:
        await state.set_state(None)
