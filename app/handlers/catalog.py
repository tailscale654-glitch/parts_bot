"""Каталог: Модель → Узел → Деталь → Карточка детали."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CarModel, Part, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.catalog import CatalogRepository
from app.database.repositories.stocks import StockRepository
from app.keyboards.catalog import (
    CatalogCB,
    PreorderCB,
    models_keyboard,
    nodes_keyboard,
    offers_keyboard,
    part_card_keyboard,
    parts_keyboard,
    pickup_keyboard,
)
from app.keyboards.phone import phone_keyboard
from app.services import cars
from app.services.catalog import (
    PAGE_SIZE,
    Preorder,
    offers_text,
    paginate,
    part_card_text,
    pickup_text,
    region_days,
)
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
    """Все модели — только у сотрудников дилеров (автомобиль у них не спрашиваем).
    Клиенты и администраторы видят запчасти для автомобиля из профиля (+ «Прочее»);
    другую модель — через «🚗 Изменить автомобиль»."""
    return staff_dealer_id is not None


def _repo(session: AsyncSession, user: User, full: bool) -> CatalogRepository:
    """Всем — только детали в наличии у дилеров региона из профиля (заказать можно только там).
    Администратор и сотрудник видят все модели, но тоже только наличие своего региона —
    другой регион можно посмотреть, сменив регион в профиле."""
    return CatalogRepository(session, user.region_id)


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


async def _empty_region_text(user: User, session: AsyncSession) -> str:
    """Сотруднику: в его регионе пусто — где наличие есть (или что его нет нигде: каталог не загружен)."""
    lang = user.language
    region = localized_name(user.region, lang) if user.region else i18n.t(lang, "region_not_selected")
    elsewhere = await CatalogRepository(session).regions_with_stock()
    if not elsewhere:
        return i18n.t(lang, "catalog_empty_everywhere")
    where = "\n".join(i18n.t(lang, "catalog_region_line", region=localized_name(r, lang), n=n) for r, n in elsewhere)
    return i18n.t(lang, "catalog_region_empty", region=region, where=where)


def shop_row(lang: str | None) -> list[list[InlineKeyboardButton]]:
    """«🛍 Открыть витрину» над каталогом — если витрина настроена (MINIAPP_URL в .env)."""
    from aiogram.types import WebAppInfo

    from app.config import miniapp_url

    url = miniapp_url()
    return [[InlineKeyboardButton(text=i18n.t(lang, "btn_open_shop"), web_app=WebAppInfo(url=url))]] if url else []


async def models_view(user: User, session: AsyncSession, full: bool = False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Первый экран каталога (+ сверху «🛍 Открыть витрину», если она настроена)."""
    text, kb = await _models_view(user, session, full)
    if kb is not None and kb.inline_keyboard and shop_row(user.language):
        kb.inline_keyboard = shop_row(user.language) + kb.inline_keyboard
    return text, kb


async def _models_view(user: User, session: AsyncSession, full: bool = False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Клиенту — сразу категории его модели (+ «Прочее»), всем остальным — список моделей."""
    lang = user.language
    repo = _repo(session, user, full)
    if full:
        models = await repo.list_models(lang)
        if not models:  # в регионе из профиля ни у одного дилера нет наличия (или каталог ещё не загружен)
            return await _empty_region_text(user, session), None
        return i18n.t(lang, "choose_model"), models_keyboard(models, lang)
    if cars.needs_car(user):
        return car_prompt(user)
    car = cars.car_text(user, lang)
    model = await repo.model_by_name(cars.catalog_model(user))
    other = await repo.model_by_name(ALL_MODELS[0])
    if other is not None and not await repo.list_nodes(other.id, lang):
        other = None
    nodes = await repo.list_nodes(model.id, lang, cars.carsale_code(user)) if model else []
    if not nodes:
        return i18n.t(lang, "catalog_car_empty", car=car), InlineKeyboardMarkup(inline_keyboard=_car_buttons(lang, other))
    kb = nodes_keyboard(model.id, nodes, lang)
    kb.inline_keyboard = kb.inline_keyboard[:-1] + _car_buttons(lang, other)  # вместо «Назад» — «Прочее» и смена авто
    return i18n.t(lang, "catalog_for_car", car=car), kb


async def _allowed(user: User, session: AsyncSession, model: CarModel | None, full: bool) -> bool:
    """Клиент открывает только свою модель и «Прочее» (даже по старой кнопке из другого сообщения)."""
    return model is not None and (full or model.name_ru in (cars.catalog_model(user), ALL_MODELS[0]))


def _mod(user: User, model: CarModel, full: bool) -> str | None:
    return None if full or model.name_ru != cars.catalog_model(user) else cars.carsale_code(user)


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
    full = full_access(user, settings, staff_dealer_id)
    repo = _repo(session, user, full)
    model = await repo.get_model(callback_data.model_id)
    if not await _allowed(user, session, model, full):
        await _unavailable(callback, lang)
        return
    if not full and model.name_ru == cars.catalog_model(user):  # своя модель — главный экран каталога клиента
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
    full = full_access(user, settings, staff_dealer_id)
    repo = _repo(session, user, full)
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


async def preorder_for(session: AsyncSession, part: Part, user: User) -> Preorder | None:
    """Деталь есть на складе JAC и в регионе покупателя есть дилер, к которому её привезут."""
    stocks = StockRepository(session)
    stock = await stocks.warehouse_offer(part.id)
    if stock is None:
        return None
    dealers = await stocks.pickup_dealers(user.region_id)
    return Preorder(stock, dealers, region_days(user.region, user.language)) if dealers else None


async def card_view(part: Part, user: User, session: AsyncSession, page: int):
    """Карточка детали → (текст, кнопки, фото). Только дилеры региона покупателя, у которых деталь есть;
    у них её нет — предзаказ со склада JAC."""
    lang = user.language
    stocks = StockRepository(session)
    offers = [o for o in await stocks.offers_in_region(part.id, user.region_id) if o.quantity > 0]
    preorder = None if offers else await preorder_for(session, part, user)
    elsewhere = 0 if offers or preorder else await stocks.regions_elsewhere(part.id, user.region_id)
    text = part_card_text(part, lang, user.region, offers, elsewhere, preorder)
    kb = part_card_keyboard(part, page, lang, offers, preorder, await CartRepository(session).total_qty(user))
    photo = part.photo if len(text) <= 1024 else None  # подпись к фото — не длиннее 1024 символов
    return text, kb, photo


@router.callback_query(CatalogCB.filter(F.action == "part"))
async def show_part(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    part = await CatalogRepository(session).get_part(callback_data.part_id)
    if part is None:
        await _unavailable(callback, lang)
        return
    text, kb, photo = await card_view(part, user, session, callback_data.page)
    await _show(callback, text, kb, photo=photo)


@router.callback_query(CatalogCB.filter(F.action == "offers"))
async def show_offers(callback: CallbackQuery, callback_data: CatalogCB, user: User, session: AsyncSession) -> None:
    """«🏢 Все дилеры»: у кого в регионе деталь есть, с адресами и кнопкой «В корзину» у каждого."""
    lang = user.language
    part = await CatalogRepository(session).get_part(callback_data.part_id)
    offers = [o for o in await StockRepository(session).offers_in_region(part.id, user.region_id)
              if o.quantity > 0] if part else []
    if not offers:
        await _unavailable(callback, lang)
        return
    qty = await CartRepository(session).total_qty(user)
    await _show(callback, offers_text(part, lang, user.region, offers),
                offers_keyboard(part, callback_data.page, lang, offers, qty))


@router.callback_query(PreorderCB.filter(F.action == "pick"))
async def preorder_pick(callback: CallbackQuery, callback_data: PreorderCB, user: User, session: AsyncSession) -> None:
    """Предзаказ: в регионе несколько дилеров — спрашиваем, у кого клиент заберёт деталь."""
    lang = user.language
    stock = await StockRepository(session).get(callback_data.stock_id)
    preorder = await preorder_for(session, stock.part, user) if stock is not None else None
    if preorder is None:
        await _unavailable(callback, lang)
        return
    await _show(callback, pickup_text(stock.part, lang, preorder), pickup_keyboard(stock.part, callback_data.page, lang, preorder))


@router.callback_query(PreorderCB.filter(F.action == "add"))
async def preorder_add(callback: CallbackQuery, callback_data: PreorderCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    stocks = StockRepository(session)
    stock = await stocks.get(callback_data.stock_id)
    dealer = await stocks.get_dealer(callback_data.dealer_id)
    if stock is None or dealer is None:
        await _unavailable(callback, lang)
        return
    ok, qty = await CartRepository(session).add(user, stock, pickup=dealer)
    if not ok:
        limit = qty and qty >= stock.quantity
        await callback.answer(i18n.t(lang, "cart_limit_preorder" if limit else "item_unavailable", qty=qty),
                              show_alert=True)
        return
    await callback.answer(i18n.t(lang, "added_preorder", qty=qty, dealer=dealer.name))
    # вернуть карточку (с кнопкой «🛒 Корзина · N шт.»): с экрана выбора дилера или обновить на месте
    text, kb, photo = await card_view(stock.part, user, session, callback_data.page)
    message = callback.message
    try:
        if message.photo:
            await message.edit_caption(caption=text[:1024], reply_markup=kb)
        elif photo:
            await message.answer_photo(photo, caption=text[:1024], reply_markup=kb)
            await _safe_delete(message)
        else:
            await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await message.answer(text, reply_markup=kb)  # битая ссылка на фото и т.п. — карточка текстом


@router.callback_query(CatalogCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
