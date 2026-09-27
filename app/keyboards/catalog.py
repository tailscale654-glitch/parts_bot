from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import CarModel, Node, Part, Stock
from app.keyboards.cart import CartCB
from app.services.catalog import MAX_OFFERS_SHOWN, Page, money
from app.services.localization import i18n, localized_name


class CatalogCB(CallbackData, prefix="cat"):
    """Кнопки каталога. Пример данных: cat:parts:3:5:0:2 (модель 3, категория 5, страница 2)."""

    action: str  # models | nodes | parts | part | noop
    model_id: int = 0
    node_id: int = 0
    part_id: int = 0
    page: int = 1


def _grid(buttons: list[InlineKeyboardButton], columns: int = 2) -> list[list[InlineKeyboardButton]]:
    """Кнопки плиткой по 2 в ряд (как в EVOS)."""
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]


def _back(lang: str, back: CatalogCB) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text=i18n.t(lang, "btn_back"), callback_data=back.pack())]]


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


def part_card_keyboard(part: Part, page: int, lang: str, offers: list[Stock] | None = None) -> InlineKeyboardMarkup:
    """Кнопка «В корзину» — у каждого дилера, у которого деталь есть в наличии."""
    rows = [
        [InlineKeyboardButton(
            text=i18n.t(lang, "btn_add_to_cart", dealer=s.dealer.name, price=money(s.price, lang)),
            callback_data=CartCB(action="add", id=s.id).pack(),
        )]
        for s in (offers or [])[:MAX_OFFERS_SHOWN]
        if s.quantity > 0
    ]
    back = CatalogCB(action="parts", model_id=part.model_id, node_id=part.node_id, page=page)
    return InlineKeyboardMarkup(inline_keyboard=rows + _back(lang, back))
