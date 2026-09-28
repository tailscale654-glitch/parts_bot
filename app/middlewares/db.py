"""Для каждого сообщения открывает сессию БД и загружает пользователя.
Handlers получают готовые аргументы `session`, `user` и `staff_dealer_id`.
Заблокированным в веб-панели бот не отвечает (кроме администраторов из ADMIN_IDS)."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.repositories.staff import StaffRepository
from app.database.repositories.users import UserRepository
from app.services.localization import i18n


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            tg_user = data.get("event_from_user")
            if tg_user is not None and not tg_user.is_bot:
                user = await UserRepository(session).get_or_create(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    last_name=tg_user.last_name,
                )
                settings = data.get("settings")
                admin_ids = settings.admin_ids if settings is not None else set()
                if user.blocked and user.telegram_id not in admin_ids:
                    return await self._refuse(event, user.language)
                data["user"] = user
                # id дилера, если пользователь — сотрудник дилера (иначе None)
                data["staff_dealer_id"] = await StaffRepository(session).dealer_id_for(user)
            return await handler(event, data)

    @staticmethod
    async def _refuse(event: TelegramObject, lang: str | None) -> None:
        """Сообщение — короткий ответ; нажатие кнопки — всплывающее окно; остальное молча пропускаем."""
        text = i18n.t(lang, "user_blocked")
        if isinstance(event, Update):
            if event.message is not None:
                await event.message.answer(text)
            elif event.callback_query is not None:
                await event.callback_query.answer(text, show_alert=True)
