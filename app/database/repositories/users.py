"""Работа с таблицей users. Handlers не пишут SQL напрямую — только через этот класс."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SUPPORTED_LANGUAGES, Region, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, region=None)
            self.session.add(user)
        # Обновляем профиль из Telegram (обрезаем длину — данным Telegram не доверяем)
        user.username = (username or None) and username[:64]
        user.first_name = (first_name or None) and first_name[:128]
        user.last_name = (last_name or None) and last_name[:128]
        await self.session.commit()
        return user

    async def set_language(self, user: User, language: str) -> User:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language!r}")
        user.language = language  # остальные поля (регион, телефон, заказы) не трогаем
        await self.session.commit()
        return user

    async def set_region(self, user: User, region: Region) -> User:
        user.region_id = region.id  # язык, телефон и заказы не трогаем
        user.region = region
        await self.session.commit()
        return user
