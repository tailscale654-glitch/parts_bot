"""Каталог: Модель → Узел → Деталь → Карточка детали."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.catalog import CatalogRepository
from app.keyboards.catalog import (
    CatalogCB,
    models_keyboard,
    nodes_keyboard,
    part_card_keyboard,
    parts_keyboard,
)
from app.keyboards.phone import phone_keyboard
from app.services.catalog import PAGE_SIZE, paginate, part_card_text
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


async def models_view(user: User, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    """Первый экран каталога — список моделей."""
    lang = user.language
    models = await CatalogRepository(session).list_models(lang)
    if not models:
        return i18n.t(lang, "catalog_empty"), None
    return i18n.t(lang, "choose_model"), models_keyboard(models, lang)


@router.callback_query(F.data == "menu:catalog")
@router.callback_query(CatalogCB.filter(F.action == "models"))
async def show_models(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not user.phone:  # каталог — только после регистрации с номером телефона
        await callback.answer()
        await callback.message.answer(
            i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language)
        )
        return
    text, kb = await models_view(user, session)
    await _show(callback, text, kb)


@router.callback_query(CatalogCB.filter(F.action == "nodes"))
async def show_nodes(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    repo = CatalogRepository(session)
    model = await repo.get_model(callback_data.model_id)
    nodes = await repo.list_nodes(model.id, lang) if model else []
    if not nodes:
        await _unavailable(callback, lang)
        return
    text = i18n.t(lang, "choose_node", model=localized_name(model, lang))
    await _show(callback, text, nodes_keyboard(model.id, nodes, lang))


@router.callback_query(CatalogCB.filter(F.action == "parts"))
async def show_parts(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    repo = CatalogRepository(session)
    model = await repo.get_model(callback_data.model_id)
    node = await repo.get_node(callback_data.node_id)
    total = await repo.count_parts(model.id, node.id) if model and node else 0
    if not total:
        await _unavailable(callback, lang)
        return
    page = paginate(total, callback_data.page)
    parts = await repo.list_parts(model.id, node.id, lang, page.offset, PAGE_SIZE)
    text = i18n.t(lang, "choose_part", model=localized_name(model, lang), node=localized_name(node, lang))
    await _show(callback, text, parts_keyboard(model.id, node.id, parts, page, lang))


@router.callback_query(CatalogCB.filter(F.action == "part"))
async def show_part(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    part = await CatalogRepository(session).get_part(callback_data.part_id)
    if part is None:
        await _unavailable(callback, lang)
        return
    await _show(callback, part_card_text(part, lang), part_card_keyboard(part, callback_data.page, lang), photo=part.photo)


@router.callback_query(CatalogCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
