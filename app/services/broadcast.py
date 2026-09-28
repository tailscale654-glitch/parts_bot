"""Рассылка клиентам из веб-панели: кому отправлять и сама отправка (в фоне, ~20 сообщений в секунду)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Broadcast, Order, Region, User
from app.services.notify import send

logger = logging.getLogger(__name__)
DELAY = 0.05  # Telegram разрешает ~30 сообщений в секунду; держимся с запасом
LANG_NAMES = {"ru": "русский", "uz": "узбекский", "en": "английский"}


@dataclass
class Audience:
    region_id: int | None = None
    language: str = ""  # ru | uz | en | "" — все
    buyers_only: bool = False  # только те, кто уже делал заказ

    def query(self):
        """Зарегистрированные (с телефоном), не заблокированные клиенты под фильтр."""
        q = select(User.telegram_id).where(User.phone.is_not(None), User.blocked.is_(False))
        if self.region_id:
            q = q.where(User.region_id == self.region_id)
        if self.language:
            q = q.where(User.language == self.language)
        if self.buyers_only:
            q = q.where(select(Order.id).where(Order.user_id == User.id).exists())
        return q

    async def count(self, session: AsyncSession) -> int:
        return await session.scalar(select(func.count()).select_from(self.query().subquery())) or 0

    async def telegram_ids(self, session: AsyncSession) -> list[int]:
        return list(await session.scalars(self.query().order_by(User.id)))

    async def describe(self, session: AsyncSession) -> str:
        parts = []
        if self.region_id:
            region = await session.get(Region, self.region_id)
            parts.append(f"регион: {region.name_ru if region else '?'}")
        if self.language:
            parts.append(f"язык: {LANG_NAMES.get(self.language, self.language)}")
        if self.buyers_only:
            parts.append("только покупатели")
        return ", ".join(parts) or "все клиенты"


async def run(broadcast_id: int, chat_ids: list[int], text: str, bot: Bot, session_factory: async_sessionmaker) -> None:
    """Отправить всем по очереди; прогресс пишется в базу каждые 20 сообщений."""
    sent = failed = 0

    async def save(**extra) -> None:
        async with session_factory() as s:
            await s.execute(update(Broadcast).where(Broadcast.id == broadcast_id)
                            .values(sent=sent, failed=failed, **extra))
            await s.commit()

    try:
        for i, chat_id in enumerate(chat_ids, start=1):
            if await send(bot, chat_id, text):
                sent += 1
            else:
                failed += 1
            if i % 20 == 0:
                await save()
            await asyncio.sleep(DELAY)
        await save(status="done", finished_at=datetime.now(timezone.utc))
        logger.info("Broadcast %s done: %s sent, %s failed", broadcast_id, sent, failed)
    except Exception:
        logger.exception("Broadcast %s failed", broadcast_id)
        await save(status="interrupted", finished_at=datetime.now(timezone.utc))


async def mark_interrupted(session: AsyncSession) -> None:
    """При запуске панели: рассылки, прерванные перезапуском, помечаем как прерванные."""
    await session.execute(update(Broadcast).where(Broadcast.status == "sending")
                          .values(status="interrupted", finished_at=datetime.now(timezone.utc)))
    await session.commit()
