from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import CarModel, Node, Part
from app.services.catalog import Page
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
    # Названия деталей длинные — по одной в ряд
    rows = [
        [InlineKeyboardButton(
            text=localized_name(p, lang),
            callback_data=CatalogCB(action="part", part_id=p.id, page=page.number).pack(),
        )]
        for p in parts
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


def part_card_keyboard(part: Part, page: int, lang: str) -> InlineKeyboardMarkup:
    back = CatalogCB(action="parts", model_id=part.model_id, node_id=part.node_id, page=page)
    return InlineKeyboardMarkup(inline_keyboard=_back(lang, back))
