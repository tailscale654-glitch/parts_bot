"""Запросы веб-панели: заказы с фильтрами и поиском, переписка по заказу."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, Order, OrderItem, OrderMessage, Region, User
from app.database.repositories.admin import ORDER_FILTERS


@dataclass
class OrderFilters:
    tab: str = "all"  # new | work | done | cancel | all
    dealer_id: int | None = None
    region_id: int | None = None  # регион дилера
    date_from: date | None = None
    date_to: date | None = None  # включительно
    q: str = ""  # номер заказа, телефон, имя клиента, артикул или название детали

    def as_query(self) -> dict[str, str]:
        """Для ссылок «следующая страница» и «выгрузить в Excel» с теми же фильтрами."""
        params = {"tab": self.tab, "q": self.q}
        if self.dealer_id:
            params["dealer_id"] = str(self.dealer_id)
        if self.region_id:
            params["region_id"] = str(self.region_id)
        if self.date_from:
            params["date_from"] = self.date_from.isoformat()
        if self.date_to:
            params["date_to"] = self.date_to.isoformat()
        return {k: v for k, v in params.items() if v}


def _local_midnight_utc(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


class PanelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def orders_query(self, f: OrderFilters, tz: ZoneInfo):
        query = select(Order).join(User, User.id == Order.user_id).join(Dealer, Dealer.id == Order.dealer_id)
        statuses = ORDER_FILTERS.get(f.tab, ())
        if statuses:
            query = query.where(Order.status.in_(statuses))
        if f.dealer_id:
            query = query.where(Order.dealer_id == f.dealer_id)
        if f.region_id:
            query = query.where(Dealer.region_id == f.region_id)
        if f.date_from:
            query = query.where(Order.created_at >= _local_midnight_utc(f.date_from, tz))
        if f.date_to:
            query = query.where(Order.created_at < _local_midnight_utc(f.date_to + timedelta(days=1), tz))
        q = f.q.strip().lstrip("№#")
        if q:
            like = f"%{q.lower()}%"
            item_match = select(OrderItem.id).where(
                OrderItem.order_id == Order.id,
                or_(func.lower(OrderItem.part_number).like(like), func.lower(OrderItem.name_ru).like(like),
                    func.lower(OrderItem.name_uz).like(like), func.lower(OrderItem.name_en).like(like)),
            ).exists()
            conditions = [
                item_match,
                func.lower(func.coalesce(User.first_name, "")).like(like),
                func.lower(func.coalesce(User.last_name, "")).like(like),
                func.lower(func.coalesce(User.username, "")).like(like),
            ]
            digits = "".join(ch for ch in q if ch.isdigit())
            if digits:
                conditions.append(func.coalesce(User.phone, "").like(f"%{digits}%"))
                if digits == q and len(digits) <= 9:
                    conditions.append(Order.id == int(digits))
            query = query.where(or_(*conditions))
        return query

    async def orders(self, f: OrderFilters, tz: ZoneInfo, offset: int, limit: int) -> tuple[list[Order], int]:
        query = self.orders_query(f, tz)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))
        return list(result.unique()), total

    async def orders_all(self, f: OrderFilters, tz: ZoneInfo, limit: int = 20000) -> list[Order]:
        result = await self.session.scalars(self.orders_query(f, tz).order_by(Order.id).limit(limit))
        return list(result.unique())

    async def dealers(self) -> list[Dealer]:
        result = await self.session.scalars(
            select(Dealer).join(Region, Region.id == Dealer.region_id).order_by(Region.sort_order, Dealer.name))
        return list(result.unique())

    async def regions(self) -> list[Region]:
        result = await self.session.scalars(select(Region).order_by(Region.sort_order))
        return list(result)

    async def messages(self, order_id: int) -> list[tuple[OrderMessage, User | None]]:
        result = await self.session.execute(
            select(OrderMessage, User).outerjoin(User, User.id == OrderMessage.sender_id)
            .where(OrderMessage.order_id == order_id).order_by(OrderMessage.id))
        return [(m, u) for m, u in result.unique().all()]
