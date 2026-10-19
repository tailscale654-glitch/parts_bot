"""Чат с клиентами (раздел «💬 Чат» веб-панели).

Клиент пишет боту что угодно (текст, фото, файл, голосовое) — сообщение попадает в его диалог.
Сотрудник отвечает из панели — бот доставляет ответ клиенту в Telegram от имени «Менеджер JAC Motors».
Заметки (note) видят только сотрудники. Один диалог на клиента; закрытый диалог открывается снова,
когда клиент напишет.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SupportChat, SupportMessage, User, WebUser
from app.services.localization import i18n

logger = logging.getLogger(__name__)
MAX_TEXT = 3500
FILE_PLACEHOLDERS = {"photo": "📷 Фото", "document": "📎 Файл", "voice": "🎤 Голосовое", "video": "🎬 Видео",
                     "sticker": "🙂 Стикер", "video_note": "🎬 Видеосообщение", "audio": "🎵 Аудио"}
# быстрые ответы в панели (кнопки над полем ввода) — текст можно поправить перед отправкой
QUICK_REPLIES = [
    "Здравствуйте! Чем можем помочь?",
    "Уточните, пожалуйста, модель автомобиля и год выпуска (или VIN).",
    "Пришлите, пожалуйста, фото детали или артикул.",
    "Деталь есть в наличии. Оформить заказ можно в боте: 🛍 Каталог.",
    "Assalomu alaykum! Qanday yordam bera olamiz?",
]
TABS = {"open": "Открытые", "unread": "Непрочитанные", "mine": "Мои", "closed": "Закрытые", "all": "Все"}


def snippet(text: str, kind: str | None = None) -> str:
    label = FILE_PLACEHOLDERS.get(kind or "", "")
    body = " ".join((text or "").split())
    return (f"{label} {body}" if label and body else label or body)[:200]


async def chat_for(session: AsyncSession, user: User) -> SupportChat:
    chat = await session.scalar(select(SupportChat).where(SupportChat.user_id == user.id))
    if chat is None:
        chat = SupportChat(user_id=user.id, user=user)
        session.add(chat)
        await session.flush()
    return chat


@dataclass
class Incoming:
    chat: SupportChat
    message: SupportMessage
    first_unread: bool  # до этого всё было прочитано — пора уведомить и подтвердить клиенту


async def add_incoming(session: AsyncSession, user: User, text: str = "", file_id: str | None = None,
                       kind: str | None = None, file_name: str | None = None) -> Incoming:
    chat = await chat_for(session, user)
    first = chat.unread == 0 or chat.status == "closed"
    msg = SupportMessage(chat_id=chat.id, direction="in", text=(text or "")[:4000], file_id=file_id,
                         file_kind=kind, file_name=(file_name or None) and file_name[:255])
    session.add(msg)
    chat.status, chat.unread = "open", chat.unread + 1
    chat.last_text, chat.last_message_at = snippet(text, kind), datetime.now(timezone.utc)
    await session.commit()
    return Incoming(chat, msg, first)


@dataclass
class Upload:
    data: bytes
    name: str
    content_type: str


async def reply(bot: Bot, session: AsyncSession, chat: SupportChat, author: WebUser, text: str,
                upload: Upload | None = None, note: bool = False) -> SupportMessage:
    """Ответ клиенту (или заметка). Отвечающий становится ответственным, если ответственного нет."""
    text = (text or "").strip()[:MAX_TEXT]
    if not text and upload is None:
        raise ValueError("Пустое сообщение")
    msg = SupportMessage(chat_id=chat.id, direction="note" if note else "out", text=text, web_user_id=author.id)
    if upload is not None:
        msg.file_name = upload.name[:255]
        msg.file_kind = "photo" if upload.content_type.startswith("image/") and not upload.name.lower().endswith(
            (".gif", ".svg")) else "document"
    if not note:
        msg.delivered, sent_file_id = await _deliver(bot, chat.user, text, upload, msg.file_kind)
        msg.file_id = sent_file_id
        if chat.assigned_to is None:
            chat.assigned_to = author.id
        chat.status = "open"
        chat.last_text = snippet(("Вы: " + text) if text else "", msg.file_kind)
        chat.last_message_at = datetime.now(timezone.utc)
    session.add(msg)
    await session.commit()
    return msg


async def _deliver(bot: Bot, client: User, text: str, upload: Upload | None, kind: str | None):
    header = i18n.t(client.language, "support_reply_header")
    body = f"{header}\n\n{text}" if text else header
    try:
        if upload is None:
            await bot.send_message(client.telegram_id, body)
            return True, None
        file = BufferedInputFile(upload.data, filename=upload.name)
        if kind == "photo":
            sent = await bot.send_photo(client.telegram_id, file, caption=body[:1024])
            return True, sent.photo[-1].file_id if getattr(sent, "photo", None) else None
        sent = await bot.send_document(client.telegram_id, file, caption=body[:1024])
        return True, sent.document.file_id if getattr(sent, "document", None) else None
    except TelegramAPIError as e:
        logger.warning("Support reply to %s failed: %s", client.telegram_id, e)
        return False, None


async def mark_read(session: AsyncSession, chat: SupportChat) -> None:
    if chat.unread:
        chat.unread = 0
        await session.commit()


async def set_status(session: AsyncSession, chat: SupportChat, action: str, me: WebUser) -> str:
    if action == "assign_me":
        chat.assigned_to, chat.assignee, note = me.id, me, "Диалог закреплён за вами."
    elif action == "unassign":
        chat.assigned_to, chat.assignee, note = None, None, "Ответственный снят."
    elif action == "close":
        chat.status, chat.unread, note = "closed", 0, "Диалог закрыт. Если клиент напишет снова — откроется сам."
    elif action == "open":
        chat.status, note = "open", "Диалог снова открыт."
    else:
        raise ValueError(action)
    await session.commit()
    return note


def _filtered(query, tab: str, me_id: int, q: str):
    if tab == "open":
        query = query.where(SupportChat.status == "open")
    elif tab == "unread":
        query = query.where(SupportChat.unread > 0)
    elif tab == "mine":
        query = query.where(SupportChat.assigned_to == me_id, SupportChat.status == "open")
    elif tab == "closed":
        query = query.where(SupportChat.status == "closed")
    q = (q or "").strip().lower().lstrip("@")
    if q:
        like = f"%{q}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        conds = [func.lower(func.coalesce(User.first_name, "")).like(like),
                 func.lower(func.coalesce(User.last_name, "")).like(like),
                 func.lower(func.coalesce(User.username, "")).like(like)]
        if digits:
            conds.append(func.coalesce(User.phone, "").like(f"%{digits}%"))
        query = query.where(or_(*conds))
    return query


async def chats(session: AsyncSession, tab: str, me_id: int, q: str = "", limit: int = 100) -> list[SupportChat]:
    query = _filtered(select(SupportChat).join(User, User.id == SupportChat.user_id), tab, me_id, q)
    query = query.order_by((SupportChat.unread > 0).desc(), SupportChat.last_message_at.desc()).limit(limit)
    return list((await session.scalars(query)).unique())


async def counts(session: AsyncSession, me_id: int) -> dict[str, int]:
    result = {}
    for tab in TABS:
        query = _filtered(select(func.count(SupportChat.id)).join(User, User.id == SupportChat.user_id), tab, me_id, "")
        result[tab] = await session.scalar(query) or 0
    result["unread_messages"] = await session.scalar(select(func.coalesce(func.sum(SupportChat.unread), 0))) or 0
    return result


async def messages(session: AsyncSession, chat_id: int, after_id: int = 0, limit: int = 300) -> list[SupportMessage]:
    rows = await session.scalars(select(SupportMessage).where(SupportMessage.chat_id == chat_id,
                                                              SupportMessage.id > after_id)
                                 .order_by(SupportMessage.id.desc()).limit(limit))
    return list(reversed(list(rows.unique())))
