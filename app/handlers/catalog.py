"""Каталог: Модель → Узел → Деталь → Карточка детали."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CarModel, User
from app.database.repositories.catalog import CatalogRepository
from app.database.repositories.stocks import StockRepository
from app.keyboards.catalog import (
    CatalogCB,
    models_keyboard,
    nodes_keyboard,
    part_card_keyboard,
    parts_keyboard,
)
from app.keyboards.phone import phone_keyboard
from app.services import cars
from app.services.catalog import PAGE_SIZE, paginate, part_card_text
from app.services.import_mapping import ALL_MODELS
from app.services.localization import i18n, localized_name

router = Router(name="catalog")


async def _show(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None, photo: str | None = None) -> None:
    """Показать экран каталога на месте старого сообщения.
    Текст меняем через edit; если нужно фото (или было фото) — удаляем и отправляем заново,
    потому что Telegram не умеет превращать текстовое сообщение в фото и обратно."""
    message = callback.message
    await callback.answer()
    if photo:
        try:
            await message.answer_photo(photo, caption=text[:1024], reply_markup=kb)
            await _safe_delete(message)
            return
        except TelegramBadRequest:
            pass  # битая ссылка на фото — показываем карточку без фото
    if photo or message.photo:
        await message.answer(text, reply_markup=kb)
        await _safe_delete(message)
        return
    try:
        await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):  # повторное нажатие той же кнопки — не ошибка
            raise


async def _safe_delete(message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # сообщение уже удалено или слишком старое (>48 ч)


async def _unavailable(callback: CallbackQuery, lang: str) -> None:
    await callback.answer(i18n.t(lang, "item_unavailable"), show_alert=True)


def full_access(user: User, settings: Settings | None, staff_dealer_id: int | None) -> bool:
    """Администраторы и сотрудники дилеров видят весь каталог; клиенты — только свою модель."""
    return staff_dealer_id is not None or (settings is not None and user.telegram_id in settings.admin_ids)


def car_prompt(user: User) -> tuple[str, InlineKeyboardMarkup]:
    from app.keyboards.car import models_keyboard as car_models_keyboard

    return i18n.t(user.language, "choose_car_model"), car_models_keyboard()


def _car_buttons(lang: str | None, other: CarModel | None) -> list[list[InlineKeyboardButton]]:
    from app.keyboards.car import CarCB

    rows = []
    if other is not None:
        rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_other_parts"),
                                          callback_data=CatalogCB(action="nodes", model_id=other.id).pack())])
    rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_change_car"), callback_data=CarCB(action="start").pack())])
    return rows


async def models_view(user: User, session: AsyncSession, full: bool = False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Первый экран каталога. Клиенту — сразу категории его модели (+ «Прочее»), всем остальным — список моделей."""
    lang = user.language
    repo = CatalogRepository(session)
    if full:
        models = await repo.list_models(lang)
        if not models:
            return i18n.t(lang, "catalog_empty"), None
        return i18n.t(lang, "choose_model"), models_keyboard(models, lang)
    if cars.needs_car(user):
        return car_prompt(user)
    car = cars.car_text(user, lang)
    model = await repo.model_by_name(user.car_model)
    other = await repo.model_by_name(ALL_MODELS[0])
    if other is not None and not await repo.list_nodes(other.id, lang):
        other = None
    nodes = await repo.list_nodes(model.id, lang, user.car_modification) if model else []
    if not nodes:
        return i18n.t(lang, "catalog_car_empty", car=car), InlineKeyboardMarkup(inline_keyboard=_car_buttons(lang, other))
    kb = nodes_keyboard(model.id, nodes, lang)
    kb.inline_keyboard = kb.inline_keyboard[:-1] + _car_buttons(lang, other)  # вместо «Назад» — «Прочее» и смена авто
    return i18n.t(lang, "catalog_for_car", car=car), kb


async def _allowed(user: User, session: AsyncSession, model: CarModel | None, full: bool) -> bool:
    """Клиент открывает только свою модель и «Прочее» (даже по старой кнопке из другого сообщения)."""
    return model is not None and (full or model.name_ru in (user.car_model, ALL_MODELS[0]))


def _mod(user: User, model: CarModel, full: bool) -> str | None:
    return None if full or model.name_ru != user.car_model else user.car_modification


@router.callback_query(F.data == "menu:catalog")
@router.callback_query(CatalogCB.filter(F.action == "models"))
async def show_models(callback: CallbackQuery, user: User, session: AsyncSession,
                      settings: Settings | None = None, staff_dealer_id: int | None = None) -> None:
    if not user.phone:  # каталог — только после регистрации с номером телефона
        await callback.answer()
        await callback.message.answer(
            i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language)
        )
        return
    text, kb = await models_view(user, session, full_access(user, settings, staff_dealer_id))
    await _show(callback, text, kb)


@router.callback_query(CatalogCB.filter(F.action == "nodes"))
async def show_nodes(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession,
                     settings: Settings | None = None, staff_dealer_id: int | None = None) -> None:
    lang = user.language
    repo = CatalogRepository(session)
    full = full_access(user, settings, staff_dealer_id)
    model = await repo.get_model(callback_data.model_id)
    if not await _allowed(user, session, model, full):
        await _unavailable(callback, lang)
        return
    if not full and model.name_ru == user.car_model:  # своя модель — главный экран каталога клиента
        text, kb = await models_view(user, session)
        await _show(callback, text, kb)
        return
    nodes = await repo.list_nodes(model.id, lang, _mod(user, model, full))
    if not nodes:
        await _unavailable(callback, lang)
        return
    text = i18n.t(lang, "choose_node", model=localized_name(model, lang))
    await _show(callback, text, nodes_keyboard(model.id, nodes, lang))


@router.callback_query(CatalogCB.filter(F.action == "parts"))
async def show_parts(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession,
                     settings: Settings | None = None, staff_dealer_id: int | None = None) -> None:
    lang = user.language
    repo = CatalogRepository(session)
    full = full_access(user, settings, staff_dealer_id)
    model = await repo.get_model(callback_data.model_id)
    node = await repo.get_node(callback_data.node_id)
    if not await _allowed(user, session, model, full):
        await _unavailable(callback, lang)
        return
    mod = _mod(user, model, full)
    total = await repo.count_parts(model.id, node.id, mod) if node else 0
    if not total:
        await _unavailable(callback, lang)
        return
    page = paginate(total, callback_data.page)
    parts = await repo.list_parts(model.id, node.id, lang, page.offset, PAGE_SIZE, mod)
    text = i18n.t(lang, "choose_part", model=localized_name(model, lang), node=localized_name(node, lang))
    await _show(callback, text, parts_keyboard(model.id, node.id, parts, page, lang))


@router.callback_query(CatalogCB.filter(F.action == "part"))
async def show_part(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    part = await CatalogRepository(session).get_part(callback_data.part_id)
    if part is None:
        await _unavailable(callback, lang)
        return
    stocks = StockRepository(session)
    offers = await stocks.offers_in_region(part.id, user.region_id)  # только дилеры региона покупателя
    elsewhere = 0 if offers else await stocks.regions_elsewhere(part.id, user.region_id)
    text = part_card_text(part, lang, user.region, offers, elsewhere)
    photo = part.photo if len(text) <= 1024 else None  # подпись к фото — не длиннее 1024 символов
    await _show(callback, text, part_card_keyboard(part, callback_data.page, lang, offers), photo=photo)


@router.callback_query(CatalogCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
