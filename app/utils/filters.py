from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Settings


class IsAdmin(BaseFilter):
    """Пропускает только Telegram ID из ADMIN_IDS (.env). Остальным бот ничего не отвечает."""

    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids
