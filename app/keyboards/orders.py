from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Order
from app.database.repositories.orders import TRANSITIONS
from app.keyboards.cart import CartCB
from app.services.localization import i18n


class OrderCB(CallbackData, prefix="ord"):
    action: str  # confirm | list | show | cancel
    id: int = 0


class AdminOrderCB(CallbackData, prefix="ost"):
    """Кнопки статуса в уведомлении администратора."""
    id: int
    status: str


def checkout_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "btn_confirm_order"), callback_data=OrderCB(action="confirm").pack())],
        [InlineKeyboardButton(text=i18n.t(lang, "btn_back_to_cart"), callback_data=CartCB(action="show").pack())],
    ])


def back_to_cart_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "btn_back_to_cart"), callback_data=CartCB(action="show").pack())],
    ])


def orders_list_keyboard(orders: list[Order], lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"№{o.id} · {i18n.t(lang, f'status_{o.status}').split(' —')[0]}",
            callback_data=OrderCB(action="show", id=o.id).pack(),
        )]
        for o in orders
    ])


def order_keyboard(order: Order, lang: str) -> InlineKeyboardMarkup:
    rows = []
    if order.status == "NEW":  # клиент может отменить, пока заказ не подтвердили
        rows.append([InlineKeyboardButton(
            text=i18n.t(lang, "btn_cancel_order"), callback_data=OrderCB(action="cancel", id=order.id).pack()
        )])
    rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_back_to_orders"), callback_data=OrderCB(action="list").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


STATUS_ORDER = ["CONFIRMED", "READY", "COMPLETED", "CANCELLED"]


def admin_order_keyboard(order: Order, lang: str) -> InlineKeyboardMarkup | None:
    allowed = [s for s in STATUS_ORDER if s in TRANSITIONS.get(order.status, set())]
    if not allowed:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=i18n.t(lang, f"btn_st_{s}"), callback_data=AdminOrderCB(id=order.id, status=s).pack())
        for s in allowed
    ]])
