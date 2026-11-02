from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import CarModel, Node, Part, Stock
from app.keyboards.cart import CartCB
from app.services.catalog import MAX_OFFERS_SHOWN, Page, Preorder, money
from app.services.localization import i18n, localized_name

FROM_SEARCH = 0  # page=0 в кнопке детали: открыли из поиска — «Назад» ведёт к результатам


class CatalogCB(CallbackData, prefix="cat"):
    """Кнопки каталога. Пример данных: cat:parts:3:5:0:2 (модель 3, категория 5, страница 2)."""

    action: str  # models | nodes | parts | part | offers | noop
    model_id: int = 0
    node_id: int = 0
    part_id: int = 0
    page: int = 1


class PreorderCB(CallbackData, prefix="pre"):
    """Предзаказ со склада JAC: pick — выбрать дилера выдачи, add — в корзину с этим дилером."""

    action: str  # pick | add
    stock_id: int
    dealer_id: int = 0
    page: int = 1


class SearchCB(CallbackData, prefix="srch"):
    action: str  # results | manager
    page: int = 1


def _grid(buttons: list[InlineKeyboardButton], columns: int = 2) -> list[list[InlineKeyboardButton]]:
    """Кнопки плиткой по 2 в ряд (как в EVOS)."""
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]


def _back(lang: str, back: CallbackData, key: str = "btn_back") -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text=i18n.t(lang, key), callback_data=back.pack())]]


def models_keyboard(models: list[CarModel], lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=localized_name(m, lang), callback_data=CatalogCB(action="nodes", model_id=m.id).pack())
        for m in models
    ]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons))


def nodes_keyboard(model_id: int, nodes: list[Node], lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=localized_name(n, lang),
            callback_data=CatalogCB(action="parts", model_id=model_id, node_id=n.id).pack(),
        )
        for n in nodes
    ]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons) + _back(lang, CatalogCB(action="models")))


def parts_keyboard(model_id: int, node_id: int, parts: list[Part], page: Page, lang: str) -> InlineKeyboardMarkup:
    # Названия деталей длинные — по одной в ряд.
    # Если у разных артикулов одинаковое название — добавляем артикул, чтобы кнопки различались.
    names = [localized_name(p, lang) for p in parts]
    rows = [
        [InlineKeyboardButton(
            text=f"{name} · {p.part_number}" if names.count(name) > 1 else name,
            callback_data=CatalogCB(action="part", part_id=p.id, page=page.number).pack(),
        )]
        for p, name in zip(parts, names)
    ]
    if page.total_pages > 1:
        def page_btn(text: str, number: int) -> InlineKeyboardButton:
            return InlineKeyboardButton(
                text=text,
                callback_data=CatalogCB(action="parts", model_id=model_id, node_id=node_id, page=number).pack(),
            )

        noop = CatalogCB(action="noop").pack()
        rows.append([
            page_btn("◀️", page.number - 1) if page.has_prev else InlineKeyboardButton(text="·", callback_data=noop),
            InlineKeyboardButton(text=f"{page.number} / {page.total_pages}", callback_data=noop),
            page_btn("▶️", page.number + 1) if page.has_next else InlineKeyboardButton(text="·", callback_data=noop),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows + _back(lang, CatalogCB(action="nodes", model_id=model_id)))


def back_to_list(part: Part, page: int) -> CallbackData:
    """Куда ведёт «Назад» из карточки: к результатам поиска или к списку деталей категории."""
    if page == FROM_SEARCH:
        return SearchCB(action="results")
    return CatalogCB(action="parts", model_id=part.model_id, node_id=part.node_id, page=page)


def cart_row(lang: str, qty: int) -> list[list[InlineKeyboardButton]]:
    if not qty:
        return []
    return [[InlineKeyboardButton(text=i18n.t(lang, "btn_go_cart", n=qty), callback_data=CartCB(action="show").pack())]]


def part_card_keyboard(part: Part, page: int, lang: str, offers: list[Stock] | None = None,
                       preorder: Preorder | None = None, cart_qty: int = 0) -> InlineKeyboardMarkup:
    """Одна большая кнопка: «В корзину» по лучшей цене или «Заказать» со склада. Остальные дилеры — отдельно."""
    offers = [s for s in (offers or []) if s.quantity > 0]
    rows = []
    if offers:
        best = offers[0]
        rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_add_best", price=money(best.price, lang)),
                                          callback_data=CartCB(action="add", id=best.id).pack())])
        if len(offers) > 1:
            rows.append([InlineKeyboardButton(
                text=i18n.t(lang, "btn_all_dealers", n=len(offers)),
                callback_data=CatalogCB(action="offers", part_id=part.id, page=page).pack())])
    elif preorder is not None and preorder.dealers:
        one = len(preorder.dealers) == 1
        rows.append([InlineKeyboardButton(
            text=i18n.t(lang, "btn_preorder", price=money(preorder.stock.price, lang)),
            callback_data=PreorderCB(action="add" if one else "pick", stock_id=preorder.stock.id,
                                     dealer_id=preorder.dealers[0].id if one else 0, page=page).pack())])
    rows += cart_row(lang, cart_qty)
    key = "btn_back_results" if page == FROM_SEARCH else "btn_back"
    return InlineKeyboardMarkup(inline_keyboard=rows + _back(lang, back_to_list(part, page), key))


def offers_keyboard(part: Part, page: int, lang: str, offers: list[Stock], cart_qty: int = 0) -> InlineKeyboardMarkup:
    """«Все дилеры»: «В корзину» у каждого дилера, у которого деталь есть."""
    rows = [
        [InlineKeyboardButton(
            text=i18n.t(lang, "btn_add_to_cart", dealer=s.dealer.name, price=money(s.price, lang)),
            callback_data=CartCB(action="add", id=s.id).pack(),
        )]
        for s in offers[:MAX_OFFERS_SHOWN]
        if s.quantity > 0
    ]
    rows += cart_row(lang, cart_qty)
    return InlineKeyboardMarkup(inline_keyboard=rows + _back(lang, CatalogCB(action="part", part_id=part.id, page=page)))


def pickup_keyboard(part: Part, page: int, lang: str, preorder: Preorder) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🏢 {d.name}", callback_data=PreorderCB(
            action="add", stock_id=preorder.stock.id, dealer_id=d.id, page=page).pack())]
        for d in preorder.dealers[:20]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + _back(lang, CatalogCB(action="part", part_id=part.id, page=page)))


def with_cart_qty(markup: InlineKeyboardMarkup | None, lang: str, qty: int) -> InlineKeyboardMarkup | None:
    """После «В корзину»: обновить кнопку «🛒 Корзина · N шт.» в уже показанной карточке (над «Назад»)."""
    if markup is None or not markup.inline_keyboard:
        return markup
    show = CartCB(action="show").pack()
    rows = [r for r in markup.inline_keyboard if not any(b.callback_data == show for b in r)]
    return InlineKeyboardMarkup(inline_keyboard=rows[:-1] + cart_row(lang, qty) + rows[-1:])


def search_results_keyboard(parts: list[Part], lang: str, local: set[int]) -> InlineKeyboardMarkup:
    """Результаты поиска: по детали в ряд; 🚚 — есть только под заказ со склада JAC."""
    rows = [
        [InlineKeyboardButton(
            text=f"{'' if p.id in local else '🚚 '}{localized_name(p, lang)} · {p.part_number}",
            callback_data=CatalogCB(action="part", part_id=p.id, page=FROM_SEARCH).pack())]
        for p in parts
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_nothing_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "btn_search_manager"), callback_data=SearchCB(action="manager").pack())],
        [InlineKeyboardButton(text=i18n.t(lang, "btn_catalog"), callback_data="menu:catalog")],
    ])
