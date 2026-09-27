"""Оформление заказа, «Мои заказы», смена статуса администратором."""
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import User
from app.database.repositories.cart import CartRepository, is_available
from app.database.repositories.orders import CheckoutError, OrderRepository
from app.keyboards.cart import CartCB
from app.keyboards.orders import (
    AdminOrderCB,
    OrderCB,
    admin_order_keyboard,
    back_to_cart_keyboard,
    checkout_keyboard,
    order_keyboard,
    orders_list_keyboard,
)
from app.services.localization import i18n
from app.services.notify import notify_new_order, notify_status_change
from app.services.orders import checkout_preview_text, order_line, order_text, status_text, stock_problems_text

logger = logging.getLogger(__name__)
router = Router(name="orders")
LIST_LIMIT = 10


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def orders_view(user: User, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    repo = OrderRepository(session)
    orders = await repo.for_user(user, LIST_LIMIT)
    lang = user.language
    if not orders:
        return i18n.t(lang, "orders_empty"), None
    lines = [i18n.t(lang, "orders_title"), ""] + [order_line(o, lang) for o in orders]
    total = await repo.count_for_user(user)
    if total > len(orders):
        lines += ["", i18n.t(lang, "orders_more", shown=len(orders), total=total)]
    return "\n".join(lines), orders_list_keyboard(orders, lang)


# ---------- оформление ----------

@router.callback_query(CartCB.filter(F.action == "checkout"))
async def checkout_preview(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    items = await CartRepository(session).items(user)
    if not any(is_available(i.stock) for i in items):
        await callback.answer(i18n.t(user.language, "checkout_nothing"), show_alert=True)
        return
    await callback.answer()
    await _edit(callback, checkout_preview_text(items, user.language), checkout_keyboard(user.language))


@router.callback_query(OrderCB.filter(F.action == "confirm"))
async def checkout_confirm(
    callback: CallbackQuery, user: User, session: AsyncSession, bot: Bot, settings: Settings,
) -> None:
    lang = user.language
    repo = OrderRepository(session)
    try:
        orders = await repo.create_from_cart(user)
        await session.commit()
    except CheckoutError as e:
        await session.commit()  # изменений не было — просто снимаем блокировку остатков
        await callback.answer()
        await _edit(callback, stock_problems_text(e.problems, lang), back_to_cart_keyboard(lang))
        return
    if not orders:
        await callback.answer(i18n.t(lang, "checkout_nothing"), show_alert=True)
        return

    await callback.answer()
    for order in orders:
        await session.refresh(order)  # подтянуть дату создания, дилера и клиента
    header = i18n.t(lang, "order_created") if len(orders) == 1 else i18n.t(lang, "orders_created", n=len(orders))
    await _edit(callback, header, None)
    for order in orders:
        await callback.message.answer(order_text(order, lang), reply_markup=order_keyboard(order, lang))
        await notify_new_order(bot, settings, session, order)
    logger.info("User %s created orders %s", user.telegram_id, [o.id for o in orders])


# ---------- мои заказы ----------

@router.callback_query(OrderCB.filter(F.action == "list"))
async def orders_list(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    text, kb = await orders_view(user, session)
    await callback.answer()
    await _edit(callback, text, kb)


@router.callback_query(OrderCB.filter(F.action.in_({"show", "cancel"})))
async def order_show_or_cancel(
    callback: CallbackQuery, callback_data: OrderCB, user: User, session: AsyncSession, bot: Bot, settings: Settings,
) -> None:
    lang = user.language
    repo = OrderRepository(session)
    order = await repo.get(callback_data.id)
    if order is None or order.user_id != user.id:  # чужой заказ не показываем
        await callback.answer(i18n.t(lang, "order_not_found"), show_alert=True)
        return
    if callback_data.action == "cancel":
        if order.status != "NEW" or not await repo.set_status(order, "CANCELLED"):
            await callback.answer(i18n.t(lang, "order_cannot_cancel"), show_alert=True)
            return
        await session.commit()
        await callback.answer(i18n.t(lang, "order_cancelled_by_client", id=order.id))
        await notify_status_change(bot, settings, session, order, actor=user, role="client")
    else:
        await callback.answer()
    await _edit(callback, order_text(order, lang), order_keyboard(order, lang))


# ---------- администратор или сотрудник дилера меняет статус ----------

@router.callback_query(AdminOrderCB.filter())
async def set_status(
    callback: CallbackQuery, callback_data: AdminOrderCB, user: User, session: AsyncSession,
    bot: Bot, settings: Settings, staff_dealer_id: int | None,
) -> None:
    lang = user.language
    repo = OrderRepository(session)
    order = await repo.get(callback_data.id)
    is_admin = user.telegram_id in settings.admin_ids
    is_staff = order is not None and staff_dealer_id == order.dealer_id
    if order is None or not (is_admin or is_staff):  # чужой дилер или обычный клиент
        await callback.answer(i18n.t(lang, "chat_forbidden"), show_alert=True)
        return
    staff_view = is_staff and not is_admin
    if not await repo.set_status(order, callback_data.status):
        # статус уже поменял кто-то другой (или кнопка устарела)
        await callback.answer(i18n.t(lang, "admin_status_not_allowed", status=status_text(order.status, lang)), show_alert=True)
        await _edit(callback, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang, staff=staff_view))
        return
    await session.commit()
    await callback.answer(i18n.t(lang, "admin_status_set", id=order.id, status=status_text(order.status, lang)))
    await _edit(callback, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang, staff=staff_view))
    await notify_status_change(bot, settings, session, order, actor=user, role="admin" if is_admin else "staff")
    logger.info("User %s (%s) set order %s → %s", user.telegram_id, "admin" if is_admin else "staff", order.id, order.status)
