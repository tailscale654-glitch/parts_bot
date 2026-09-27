"""Корзина пользователя."""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CartItem, Stock, User


def is_available(stock: Stock) -> bool:
    return stock.quantity > 0 and stock.part.active and stock.dealer.active and stock.dealer.enabled


class CartRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def items(self, user: User) -> list[CartItem]:
        result = await self.session.scalars(
            select(CartItem).where(CartItem.user_id == user.id).order_by(CartItem.created_at, CartItem.id)
        )
        return list(result.unique())

    async def _get(self, user: User, **by) -> CartItem | None:
        query = select(CartItem).where(CartItem.user_id == user.id)
        for column, value in by.items():
            query = query.where(getattr(CartItem, column) == value)
        return (await self.session.scalars(query)).unique().one_or_none()

    async def add(self, user: User, stock: Stock) -> tuple[bool, int]:
        """+1 шт. Возвращает (получилось ли, сколько теперь в корзине). Больше остатка добавить нельзя."""
        item = await self._get(user, stock_id=stock.id)
        current = item.quantity if item else 0
        if not is_available(stock) or current + 1 > stock.quantity:
            return False, current
        if item is None:
            item = CartItem(user_id=user.id, stock_id=stock.id, quantity=0)
            self.session.add(item)
        item.quantity = current + 1
        await self.session.commit()
        return True, item.quantity

    async def change(self, user: User, item_id: int, delta: int) -> bool:
        """➕ / ➖. Ноль — позиция удаляется. Возвращает False, если упёрлись в остаток."""
        item = await self._get(user, id=item_id)  # только своя корзина — чужой id не сработает
        if item is None:
            return True
        new = item.quantity + delta
        if delta > 0 and new > item.stock.quantity:
            return False
        if new <= 0:
            await self.session.delete(item)
        else:
            item.quantity = new
        await self.session.commit()
        return True

    async def remove(self, user: User, item_id: int) -> None:
        await self.session.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.id == item_id))
        await self.session.commit()

    async def clear(self, user: User) -> None:
        await self.session.execute(delete(CartItem).where(CartItem.user_id == user.id))
        await self.session.commit()
