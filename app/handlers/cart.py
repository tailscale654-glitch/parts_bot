"""Корзина: добавить из карточки детали, ➕/➖, удалить, очистить."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.cart import CartRepository
from app.database.repositories.stocks import StockRepository
from app.keyboards.cart import CartCB, cart_keyboard
from app.services.catalog import cart_text
from app.services.localization import i18n

router = Router(name="cart")


async def cart_view(user: User, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    items = await CartRepository(session).items(user)
    if not items:
        return i18n.t(user.language, "cart_empty"), None
    return cart_text(items, user.language), cart_keyboard(items, user.language)


async def _refresh(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    text, kb = await cart_view(user, session)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(CartCB.filter(F.action != "checkout"))  # checkout — в handlers/orders.py
async def cart_action(callback: CallbackQuery, callback_data: CartCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    cart = CartRepository(session)
    action = callback_data.action

    if action == "add":
        stock = await StockRepository(session).get(callback_data.id)
        if stock is None:
            await callback.answer(i18n.t(lang, "item_unavailable"), show_alert=True)
            return
        ok, qty = await cart.add(user, stock)
        await callback.answer(i18n.t(lang, "added_to_cart" if ok else "cart_limit", qty=qty), show_alert=not ok)
        return

    if action in ("inc", "dec"):
        ok = await cart.change(user, callback_data.id, +1 if action == "inc" else -1)
        if not ok:
            await callback.answer(i18n.t(lang, "cart_limit_short"), show_alert=True)
            return
    elif action == "del":
        await cart.remove(user, callback_data.id)
    elif action == "clear":
        await cart.clear(user)
        await callback.answer(i18n.t(lang, "cart_cleared"))
        await _refresh(callback, user, session)
        return
    elif action == "show":  # «◀️ Назад в корзину» с экрана оформления
        pass
    await callback.answer()
    await _refresh(callback, user, session)
