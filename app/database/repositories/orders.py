"""Заказы: создание из корзины, смена статуса, история клиента."""
from __future__ import annotations

import os

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarsaleOp, CartItem, Order, OrderItem, Stock, User
from app.database.repositories.cart import is_available

# Какой статус можно поставить из текущего
TRANSITIONS = {
    "NEW": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"READY", "CANCELLED"},
    "READY": {"COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
FINAL_STATUSES = {"COMPLETED", "CANCELLED"}


def carsale_mode() -> str:
    """CARSALE_ORDERS в .env: off — не писать в CarSale; dry — заполнить форму без сохранения; on — записывать."""
    mode = os.getenv("CARSALE_ORDERS", "off").strip().lower()
    return mode if mode in ("off", "dry", "on") else "off"


@dataclass
class StockProblem:
    """Деталь закончилась или её стало меньше, чем в корзине. Простые значения — не зависят от сессии."""
    stock_id: int
    names: dict  # {"ru": ..., "en": ..., "uz": ...}
    wanted: int
    available: int


class CheckoutError(Exception):
    def __init__(self, problems: list[StockProblem]):
        self.problems = problems
        super().__init__(f"{len(problems)} stock problems")


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_from_cart(self, user: User) -> list[Order]:
        """Корзина → заказы (по одному на дилера). Всё в одной транзакции.

        Остаток дилера уменьшается сразу (резерв), чтобы два покупателя не купили одну деталь.
        Если чего-то не хватает — заказы не создаются, корзина не меняется, возвращается список проблем.
        """
        items = list((await self.session.scalars(
            select(CartItem).where(CartItem.user_id == user.id).order_by(CartItem.id)
        )).unique())
        if not items:
            return []

        # Блокируем строки остатков до конца транзакции (FOR UPDATE), чтобы никто не купил их параллельно
        stock_ids = [i.stock_id for i in items]
        locked = {
            s.id: s for s in (await self.session.scalars(
                select(Stock).where(Stock.id.in_(stock_ids)).with_for_update(of=Stock)
                .execution_options(populate_existing=True)  # свежие остатки из базы, а не из кэша сессии
            )).unique()
        }
        problems = []
        for item in items:
            stock = locked.get(item.stock_id)
            if stock is None or not is_available(stock) or item.quantity > stock.quantity:
                part = item.stock.part
                problems.append(StockProblem(
                    stock_id=item.stock_id,
                    names={"ru": part.name_ru, "en": part.name_en, "uz": part.name_uz},
                    wanted=item.quantity,
                    available=stock.quantity if stock is not None and is_available(stock) else 0,
                ))
        if problems:
            raise CheckoutError(problems)

        by_dealer: dict[int, list[CartItem]] = defaultdict(list)
        for item in items:
            by_dealer[locked[item.stock_id].dealer_id].append(item)

        orders = []
        for dealer_id, dealer_items in by_dealer.items():
            order = Order(user_id=user.id, dealer_id=dealer_id, status="NEW", total_amount=Decimal(0))
            for item in dealer_items:
                stock = locked[item.stock_id]
                part = stock.part
                total = stock.price * item.quantity
                order.items.append(OrderItem(
                    part_id=part.id, stock_id=stock.id, part_number=part.part_number,
                    name_ru=part.name_ru, name_en=part.name_en, name_uz=part.name_uz,
                    model_name=part.model.name_ru, node_name=part.node.name_ru,
                    quantity=item.quantity, price=stock.price, total=total,
                ))
                order.total_amount += total
                stock.quantity -= item.quantity  # резерв
            self.session.add(order)
            orders.append(order)
        await self.session.execute(delete(CartItem).where(CartItem.user_id == user.id))
        await self.session.flush()
        return orders

    async def get(self, order_id: int) -> Order | None:
        return await self.session.get(Order, order_id)

    async def for_user(self, user: User, limit: int = 10) -> list[Order]:
        result = await self.session.scalars(
            select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).limit(limit)
        )
        return list(result.unique())

    async def count_for_user(self, user: User) -> int:
        return await self.session.scalar(select(func.count(Order.id)).where(Order.user_id == user.id))

    async def set_status(self, order: Order, new_status: str) -> bool:
        """Меняет статус, если переход разрешён. При отмене возвращает детали в остаток дилера."""
        if new_status not in TRANSITIONS.get(order.status, set()):
            return False
        if new_status == "CANCELLED":
            stock_ids = [i.stock_id for i in order.items if i.stock_id]
            stocks = {
                s.id: s for s in (await self.session.scalars(
                    select(Stock).where(Stock.id.in_(stock_ids)).with_for_update(of=Stock)
                    .execution_options(populate_existing=True)
                )).unique()
            } if stock_ids else {}
            for item in order.items:
                if item.stock_id in stocks:
                    stocks[item.stock_id].quantity += item.quantity
        order.status = new_status
        if new_status == "COMPLETED" and carsale_mode() != "off":
            # выдан клиенту → сервис sync запишет продажу в CarSale (см. app/sync/carsale_orders.py)
            exists = await self.session.scalar(select(CarsaleOp.id).where(CarsaleOp.order_id == order.id))
            if exists is None:
                self.session.add(CarsaleOp(order_id=order.id, kind="sale"))
        await self.session.flush()
        return True
