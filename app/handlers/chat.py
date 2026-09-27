"""Переписка по заказу через бота. Номера и аккаунты друг друга не раскрываются,
все сообщения сохраняются в order_messages."""
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import Order, OrderMessage, User
from app.database.repositories.orders import OrderRepository
from app.handlers.start import send_main_menu
from app.keyboards.main import menu_action
from app.keyboards.orders import ChatCB, reply_keyboard
from app.services.localization import i18n
from app.services.notify import admin_recipients, person_name, staff_recipients
from app.states.admin import ChatStates

logger = logging.getLogger(__name__)
router = Router(name="chat")


def can_write(order: Order | None, to: str, user: User, settings: Settings, staff_dealer_id: int | None) -> bool:
    if order is None:
        return False
    if to == "client":  # пишет дилер или администратор
        return user.telegram_id in settings.admin_ids or staff_dealer_id == order.dealer_id
    return to == "dealer" and order.user_id == user.id  # пишет сам клиент


def cancel_keyboard(lang: str | None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=i18n.t(lang, "btn_cancel"))]],
                               resize_keyboard=True, one_time_keyboard=True)


@router.callback_query(ChatCB.filter())
async def start_writing(
    callback: CallbackQuery, callback_data: ChatCB, user: User, session: AsyncSession,
    settings: Settings, staff_dealer_id: int | None, state: FSMContext,
) -> None:
    lang = user.language
    order = await OrderRepository(session).get(callback_data.id)
    if not can_write(order, callback_data.to, user, settings, staff_dealer_id):
        await callback.answer(i18n.t(lang, "chat_forbidden"), show_alert=True)
        return
    await state.set_state(ChatStates.writing)
    await state.update_data(order_id=order.id, to=callback_data.to)
    whom = i18n.t(lang, "whom_client") if callback_data.to == "client" else i18n.t(lang, "whom_dealer", dealer=order.dealer.name)
    await callback.answer()
    await callback.message.answer(i18n.t(lang, "chat_ask", id=order.id, whom=whom), reply_markup=cancel_keyboard(lang))


@router.message(ChatStates.writing)
async def relay(
    message: Message, user: User, session: AsyncSession, bot: Bot,
    settings: Settings, staff_dealer_id: int | None, state: FSMContext,
) -> None:
    lang = user.language
    data = await state.get_data()
    await state.clear()
    if menu_action(message.text) is not None:  # «❌ Отмена» или любая кнопка меню — выходим из режима
        await send_main_menu(message, user, session, prefix=i18n.t(lang, "cancelled"))
        return
    order = await OrderRepository(session).get(data.get("order_id", 0))
    to = data.get("to")
    if not can_write(order, to, user, settings, staff_dealer_id):
        await message.answer(i18n.t(lang, "chat_forbidden"))
        return

    if to == "client":
        client = order.user
        recipients = [(client.telegram_id, client.language)]
        header_key, header_params, reply_to = "chat_to_client_header", {"id": order.id, "dealer": order.dealer.name}, "dealer"
        fallback_note = None
    else:
        recipients = await staff_recipients(session, order.dealer_id)
        fallback_note = None
        if not recipients:  # у дилера ещё нет сотрудников в боте — пишем администраторам
            recipients = await admin_recipients(session, settings)
            fallback_note = i18n.t(lang, "chat_no_staff")
        header_key, reply_to = "chat_to_dealer_header", "client"
        header_params = {"id": order.id, "name": person_name(user), "phone": user.phone or "—"}

    delivered = 0
    for chat_id, rlang in recipients:
        try:
            await bot.send_message(chat_id, i18n.t(rlang, header_key, **header_params))
            await bot.copy_message(chat_id, message.chat.id, message.message_id,
                                   reply_markup=reply_keyboard(reply_to, order.id, rlang))
            delivered += 1
        except TelegramAPIError as e:
            logger.warning("Chat relay to %s failed: %s", chat_id, e)

    session.add(OrderMessage(order_id=order.id, sender_id=user.id, to_side=to, text=message.text or message.caption))
    await session.commit()
    result = i18n.t(lang, "chat_sent") if delivered else i18n.t(lang, "chat_failed")
    if delivered and fallback_note:
        result += "\n" + fallback_note
    await send_main_menu(message, user, session, prefix=result)
