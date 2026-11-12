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
        """Новый регион. Детали дилеров прежнего региона убираем из корзины: заказать можно только в своём."""
        from app.database.repositories.cart import CartRepository

        user.region_id = region.id  # язык, телефон и заказы не трогаем
        user.region = region
        for item in await CartRepository(self.session).items(user):
            dealer = item.pickup_dealer if item.stock.dealer.is_warehouse else item.stock.dealer
            if dealer is None or dealer.region_id != region.id:
                await self.session.delete(item)
        await self.session.commit()
        return user

    async def set_car(self, user: User, **fields) -> User:
        """car_model / car_modification / car_color / car_vin / car_engine / car_trim — что передали, то и меняем.

        Сменил модель на другую — старый VIN и данные CarSale уже не от этой машины, сбрасываем их.
        """
        if "model" in fields and "vin" not in fields and fields["model"] != user.car_model:
            fields["vin"] = None
        if "vin" in fields and fields["vin"] != user.car_vin:
            fields.setdefault("engine", None)  # другой VIN — номер двигателя от прежней машины не подходит
            fields.setdefault("trim", None)
        for name, value in fields.items():
            setattr(user, f"car_{name}", value)
        await self.session.commit()
        return user

    async def set_phone(self, user: User, phone: str) -> User:
        user.phone = phone
        await self.session.commit()
        return user
