"""Корзина пользователя. Позиция — либо покупка у дилера, либо предзаказ со склада JAC
(тогда pickup_dealer — дилер, у которого клиент заберёт деталь)."""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CartItem, Dealer, Stock, User


def is_available(stock: Stock) -> bool:
    return stock.quantity > 0 and stock.part.active and stock.dealer.active and stock.dealer.enabled


def can_pickup(dealer: Dealer | None) -> bool:
    """К этому дилеру можно привезти предзаказ (условия — как в catalog.pickup_conditions)."""
    return dealer is not None and dealer.enabled and not dealer.is_warehouse and (dealer.active or dealer.in_directory)


def item_available(item: CartItem) -> bool:
    """Позицию корзины можно заказать: деталь в наличии (у дилера или на складе), дилер выдачи работает."""
    if not is_available(item.stock):
        return False
    if item.stock.dealer.is_warehouse:
        return can_pickup(item.pickup_dealer)
    return not item.preorder


class CartRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def items(self, user: User) -> list[CartItem]:
        result = await self.session.scalars(
            select(CartItem).where(CartItem.user_id == user.id).order_by(CartItem.created_at, CartItem.id)
        )
        return list(result.unique())

    async def total_qty(self, user: User) -> int:
        """Сколько штук в корзине — для кнопки «🛒 Корзина · N шт.»."""
        return await self.session.scalar(
            select(func.coalesce(func.sum(CartItem.quantity), 0)).where(CartItem.user_id == user.id)) or 0

    async def _get(self, user: User, **by) -> CartItem | None:
        query = select(CartItem).where(CartItem.user_id == user.id)
        for column, value in by.items():
            query = query.where(getattr(CartItem, column) == value)
        return (await self.session.scalars(query)).unique().one_or_none()

    async def add(self, user: User, stock: Stock, pickup: Dealer | None = None) -> tuple[bool, int]:
        """+1 шт. Возвращает (получилось ли, сколько теперь в корзине). Больше остатка добавить нельзя.
        Деталь со склада JAC — только с дилером выдачи (pickup) из региона покупателя."""
        item = await self._get(user, stock_id=stock.id)
        current = item.quantity if item else 0
        if stock.dealer.is_warehouse:
            if not can_pickup(pickup) or pickup.region_id != user.region_id:
                return False, current
        elif pickup is not None or stock.dealer.region_id != user.region_id:
            return False, current  # заказать можно только у дилеров своего региона
        if not is_available(stock) or current + 1 > stock.quantity:
            return False, current
        if item is None:
            item = CartItem(user_id=user.id, stock_id=stock.id, quantity=0)
            self.session.add(item)
        item.pickup_dealer = pickup  # предзаказ: выбрали другого дилера — запоминаем последнего
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

    async def repeat(self, user: User, order) -> tuple[int, list[str]]:
        """«🔁 Повторить заказ»: детали заказа → в корзину, сколько сейчас можно.
        Тот же дилер (или склад с тем же дилером выдачи); нет у него — лучшая цена в регионе или предзаказ.
        → (сколько позиций добавлено, названия того, чего сейчас нет)."""
        from app.database.repositories.stocks import StockRepository

        stocks = StockRepository(self.session)
        added, missing = 0, []
        for line in order.items:
            candidates = []
            if line.stock_id:
                candidates.append(await stocks.get(line.stock_id))
            if line.part_id:
                candidates += [o for o in await stocks.offers_in_region(line.part_id, user.region_id) if o.quantity > 0]
                candidates.append(await stocks.warehouse_offer(line.part_id))
            got = 0
            for stock in filter(None, candidates):
                if not stock.dealer.is_warehouse and stock.dealer.region_id != user.region_id:
                    continue  # клиент сменил регион — у дилера старого региона не заказываем
                pickup = None
                if stock.dealer.is_warehouse:  # предзаказ: забрать там же, где в прошлый раз, если тот дилер в регионе
                    pickup = order.dealer if can_pickup(order.dealer) and order.dealer.region_id == user.region_id \
                        else next(iter(await stocks.pickup_dealers(user.region_id)), None)
                while got < line.quantity:
                    ok, _ = await self.add(user, stock, pickup)
                    if not ok:
                        break
                    got += 1
                if got:
                    break
            if got:
                added += 1
            else:
                missing.append(line.name_ru if user.language in (None, "ru") else
                               getattr(line, f"name_{user.language}", None) or line.name_ru)
        return added, missing
