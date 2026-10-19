"""Сообщения клиента менеджерам: всё, что зарегистрированный клиент пишет боту (не кнопки меню),
попадает в раздел «💬 Чат» веб-панели. Ответ сотрудника приходит клиенту сюда же."""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import User
from app.services import support
from app.services.localization import i18n
from app.services.notify import admin_recipients, person_name, send

logger = logging.getLogger(__name__)
router = Router(name="support")


def registered(message: Message, user: User) -> bool:
    """Регистрацию (язык → регион → автомобиль → телефон) ведёт следующий роутер — пока она не закончена."""
    if not (user.language and user.region_id and user.phone):
        return False
    text = message.text or ""
    return not text.startswith("/")  # неизвестные команды — как раньше, подсказка с меню


def attachment(message: Message) -> tuple[str | None, str | None, str | None]:
    """(file_id, вид, имя файла)"""
    if message.photo:
        return message.photo[-1].file_id, "photo", None
    for kind in ("document", "video", "voice", "audio", "video_note", "sticker"):
        obj = getattr(message, kind, None)
        if obj is not None:
            return obj.file_id, kind, getattr(obj, "file_name", None)
    return None, None, None


@router.message(StateFilter(None), ~F.contact, registered)
async def client_writes(message: Message, user: User, session: AsyncSession, bot: Bot, settings: Settings) -> None:
    file_id, kind, name = attachment(message)
    text = message.text or message.caption or ""
    if not text and not file_id:
        return  # служебные сообщения (опрос, геопозиция и т. п.) — не сохраняем
    got = await support.add_incoming(session, user, text, file_id, kind, name)
    if not got.first_unread:
        return  # клиент пишет подряд — подтверждение и уведомление уже были
    await message.answer(i18n.t(user.language, "support_received"))
    await notify_staff(bot, settings, session, got)


async def notify_staff(bot: Bot, settings: Settings, session: AsyncSession, got: support.Incoming) -> None:
    """Администраторам и ответственному за диалог — короткое уведомление со ссылкой в панель."""
    chat, user = got.chat, got.chat.user
    link = f"\n\n{settings.web_url.rstrip('/')}/chat/{chat.id}" if settings.web_url else ""
    text = (f"💬 Новое сообщение в чате\n\n{person_name(user)} · {user.phone or '—'}\n"
            f"«{support.snippet(got.message.text, got.message.file_kind)[:300]}»{link}")
    targets = {tg for tg, _ in await admin_recipients(session, settings)}
    if chat.assignee is not None:
        targets.add(chat.assignee.user.telegram_id)
    targets.discard(user.telegram_id)
    for tg in targets:
        await send(bot, tg, text)
