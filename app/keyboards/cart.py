from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import CartItem
from app.services.localization import i18n

MAX_ITEMS_WITH_BUTTONS = 20


class CartCB(CallbackData, prefix="cart"):
    action: str  # add | inc | dec | del | clear | checkout | show | noop
    id: int = 0  # add: id предложения (stock); inc/dec/del: id позиции корзины


def cart_keyboard(items: list[CartItem], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for n, item in enumerate(items[:MAX_ITEMS_WITH_BUTTONS], start=1):
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=CartCB(action="dec", id=item.id).pack()),
            InlineKeyboardButton(text=f"{n}. × {item.quantity}", callback_data=CartCB(action="noop").pack()),
            InlineKeyboardButton(text="➕", callback_data=CartCB(action="inc", id=item.id).pack()),
            InlineKeyboardButton(text="✖️", callback_data=CartCB(action="del", id=item.id).pack()),
        ])
    rows.append([
        InlineKeyboardButton(text=i18n.t(lang, "btn_clear_cart"), callback_data=CartCB(action="clear").pack()),
        InlineKeyboardButton(text=i18n.t(lang, "btn_checkout"), callback_data=CartCB(action="checkout").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
