"""Запросы для админ-панели: заказы, дилеры, каталог, клиенты."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Dealer, Node, Order, Part, Region, Stock, User

# Вкладки заказов: ключ → статусы
ORDER_FILTERS: dict[str, tuple[str, ...]] = {
    "new": ("NEW",),
    "work": ("CONFIRMED", "READY"),
    "done": ("COMPLETED",),
    "cancel": ("CANCELLED",),
    "all": (),
}


@dataclass
class DealerRow:
    dealer: Dealer
    offers: int  # позиций с наличием
    orders: int


@dataclass
class ClientRow:
    user: User
    orders: int
    spent: Decimal


@dataclass
class CatalogSummary:
    parts_active: int
    parts_hidden: int
    offers_in_stock: int
    dealers_with_stock: int
    by_model: list[tuple[str, int]]
    by_node: list[tuple[str, int]]


class AdminRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- заказы ----------

    def _orders_query(self, key: str, user_id: int | None = None, dealer_id: int | None = None):
        query = select(Order)
        if dealer_id is not None:
            query = query.where(Order.dealer_id == dealer_id)
        statuses = ORDER_FILTERS.get(key, ())
        if statuses:
            query = query.where(Order.status.in_(statuses))
        if user_id is not None:
            query = query.where(Order.user_id == user_id)
        return query

    async def order_counts(self, dealer_id: int | None = None) -> dict[str, int]:
        query = select(Order.status, func.count()).group_by(Order.status)
        if dealer_id is not None:
            query = query.where(Order.dealer_id == dealer_id)
        rows = dict((await self.session.execute(query)).all())
        return {key: (sum(rows.values()) if not st else sum(rows.get(s, 0) for s in st))
                for key, st in ORDER_FILTERS.items()}

    async def orders_page(
        self, key: str, offset: int, limit: int, user_id: int | None = None, dealer_id: int | None = None,
    ) -> tuple[list[Order], int]:
        query = self._orders_query(key, user_id, dealer_id)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))
        return list(result.unique()), total

    # ---------- дилеры ----------

    async def dealers_page(self, offset: int, limit: int) -> tuple[list[DealerRow], int]:
        offers = (
            select(func.count(Stock.id)).where(Stock.dealer_id == Dealer.id, Stock.quantity > 0).scalar_subquery()
        )
        orders = select(func.count(Order.id)).where(Order.dealer_id == Dealer.id).scalar_subquery()
        total = await self.session.scalar(select(func.count(Dealer.id)))
        result = await self.session.execute(
            select(Dealer, offers, orders)
            .join(Region, Region.id == Dealer.region_id)
            .order_by(Region.sort_order, Dealer.name)
            .offset(offset).limit(limit)
        )
        return [DealerRow(d, o or 0, n or 0) for d, o, n in result.unique().all()], total

    async def dealer(self, dealer_id: int) -> DealerRow | None:
        dealer = await self.session.get(Dealer, dealer_id)
        if dealer is None:
            return None
        offers = await self.session.scalar(
            select(func.count(Stock.id)).where(Stock.dealer_id == dealer.id, Stock.quantity > 0)
        )
        orders = await self.session.scalar(select(func.count(Order.id)).where(Order.dealer_id == dealer.id))
        return DealerRow(dealer, offers or 0, orders or 0)

    async def toggle_dealer(self, dealer_id: int) -> Dealer | None:
        dealer = await self.session.get(Dealer, dealer_id)
        if dealer is not None:
            dealer.enabled = not dealer.enabled
            await self.session.commit()
        return dealer

    # ---------- каталог ----------

    async def catalog_summary(self) -> CatalogSummary:
        active = await self.session.scalar(select(func.count(Part.id)).where(Part.active.is_(True)))
        hidden = await self.session.scalar(select(func.count(Part.id)).where(Part.active.is_(False)))
        in_stock = select(Stock.id, Stock.dealer_id).join(Dealer, Dealer.id == Stock.dealer_id).where(
            Stock.quantity > 0, Dealer.active.is_(True), Dealer.enabled.is_(True)).subquery()
        offers = await self.session.scalar(select(func.count()).select_from(in_stock))
        dealers = await self.session.scalar(select(func.count(func.distinct(in_stock.c.dealer_id))))
        by_model = (await self.session.execute(
            select(CarModel.name_ru, func.count(Part.id)).join(Part, Part.model_id == CarModel.id)
            .where(Part.active.is_(True)).group_by(CarModel.name_ru).order_by(func.count(Part.id).desc())
        )).all()
        by_node = (await self.session.execute(
            select(Node.name_ru, func.count(Part.id)).join(Part, Part.node_id == Node.id)
            .where(Part.active.is_(True)).group_by(Node.name_ru).order_by(func.count(Part.id).desc())
        )).all()
        return CatalogSummary(active or 0, hidden or 0, offers or 0, dealers or 0,
                              [tuple(r) for r in by_model], [tuple(r) for r in by_node])

    # ---------- клиенты ----------

    async def clients_page(self, offset: int, limit: int) -> tuple[list[ClientRow], int]:
        """Клиенты с номером телефона (закончили регистрацию), новые — сверху."""
        registered = User.phone.is_not(None)
        total = await self.session.scalar(select(func.count(User.id)).where(registered))
        orders = select(func.count(Order.id)).where(Order.user_id == User.id).scalar_subquery()
        spent = (
            select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.user_id == User.id, Order.status != "CANCELLED")  # отменённые не считаем
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(User, orders, spent)
            .where(registered)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset(offset).limit(limit)
        )
        return [ClientRow(u, n, Decimal(s)) for u, n, s in result.unique().all()], total

    async def client(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def clients_total(self) -> tuple[int, int]:
        """(всего нажали /start, закончили регистрацию с телефоном)"""
        return (
            await self.session.scalar(select(func.count(User.id))),
            await self.session.scalar(select(func.count(User.id)).where(User.phone.is_not(None))),
        )
