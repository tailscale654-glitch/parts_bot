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
    """Кнопки статуса у администратора и сотрудника дилера."""
    id: int
    status: str


class ChatCB(CallbackData, prefix="chat"):
    """Написать по заказу: to=client — клиенту (от дилера/админа), to=dealer — дилеру (от клиента)."""
    to: str
    id: int


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
    if order.status != "CANCELLED":
        rows.append([InlineKeyboardButton(
            text=i18n.t(lang, "btn_chat_dealer"), callback_data=ChatCB(to="dealer", id=order.id).pack()
        )])
    if order.status == "NEW":  # клиент может отменить, пока заказ не подтвердили
        rows.append([InlineKeyboardButton(
            text=i18n.t(lang, "btn_cancel_order"), callback_data=OrderCB(action="cancel", id=order.id).pack()
        )])
    rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_back_to_orders"), callback_data=OrderCB(action="list").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


STATUS_ORDER = ["CONFIRMED", "READY", "COMPLETED", "CANCELLED"]


def admin_order_keyboard(
    order: Order, lang: str, back: str | None = None, staff: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки статуса (только разрешённые переходы), «Написать клиенту» и «назад» к списку заказов.
    staff=True — для сотрудника дилера (назад — в «Заказы дилера»)."""
    allowed = [s for s in STATUS_ORDER if s in TRANSITIONS.get(order.status, set())]
    rows = []
    if allowed:
        rows.append([
            InlineKeyboardButton(text=i18n.t(lang, f"btn_st_{s}"), callback_data=AdminOrderCB(id=order.id, status=s).pack())
            for s in allowed
        ])
    rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_chat_client"), callback_data=ChatCB(to="client", id=order.id).pack())])
    back_text, back_default = ("btn_dealer_orders", "dl:orders:all:1:0") if staff else ("btn_adm_orders", "ap:orders:all:1:0")
    rows.append([InlineKeyboardButton(text=i18n.t(lang, back_text), callback_data=back or back_default)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reply_keyboard(to: str, order_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=i18n.t(lang, "btn_reply"), callback_data=ChatCB(to=to, id=order_id).pack())
    ]])
