"""Статистика для админ-панели. Периоды считаются по местному времени (Ташкент)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, Order, OrderItem, Region, User

PERIODS = ("today", "7", "30", "all")
TOP = 10


def period_start(period: str, tz: ZoneInfo, now: datetime | None = None) -> datetime | None:
    """Начало периода в UTC. «today» — с полуночи по местному времени, «7» — последние 7 дней включая сегодня."""
    if period == "all":
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = {"today": 0, "7": 6, "30": 29}[period]
    return (midnight - timedelta(days=days)).astimezone(timezone.utc)


@dataclass
class Stats:
    orders: int = 0
    revenue: Decimal = Decimal(0)  # сумма заказов без отменённых
    completed_sum: Decimal = Decimal(0)  # сумма выданных
    avg_check: Decimal = Decimal(0)
    by_status: dict[str, int] = field(default_factory=dict)
    by_region: list[tuple[Region, int, Decimal]] = field(default_factory=list)  # регион дилера
    by_dealer: list[tuple[str, int, Decimal]] = field(default_factory=list)
    top_parts: list[tuple[str, str, int]] = field(default_factory=list)  # (название, артикул, штук)
    new_clients: int = 0
    active_clients: int = 0  # сделали хотя бы один заказ за период


@dataclass
class Day:
    day: date
    orders: int = 0  # все заказы, включая отменённые
    revenue: Decimal = Decimal(0)  # без отменённых


class StatsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.until: datetime | None = None  # конец периода (не включая); None — до сейчас

    def _since(self, query, column, since: datetime | None):
        if since is not None:
            query = query.where(column >= since)
        if self.until is not None:
            query = query.where(column < self.until)
        return query

    async def collect(self, since: datetime | None, until: datetime | None = None) -> Stats:
        self.until = until
        s = Stats()
        valid = Order.status != "CANCELLED"

        by_status = await self.session.execute(
            self._since(select(Order.status, func.count(Order.id)), Order.created_at, since).group_by(Order.status)
        )
        s.by_status = dict(by_status.all())
        s.orders = sum(s.by_status.values())

        revenue = await self.session.execute(self._since(
            select(func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id)).where(valid),
            Order.created_at, since))
        rev, valid_count = revenue.one()
        s.revenue = Decimal(rev)
        s.avg_check = (s.revenue / valid_count).quantize(Decimal(1)) if valid_count else Decimal(0)
        s.completed_sum = Decimal(await self.session.scalar(self._since(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.status == "COMPLETED"),
            Order.created_at, since)))

        region_rows = await self.session.execute(self._since(
            select(Region.id, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
            .join(Dealer, Dealer.id == Order.dealer_id).join(Region, Region.id == Dealer.region_id)
            .where(valid), Order.created_at, since)
            .group_by(Region.id).order_by(func.sum(Order.total_amount).desc()))
        for region_id, n, total in region_rows.all():
            s.by_region.append((await self.session.get(Region, region_id), n, Decimal(total)))

        dealer_rows = await self.session.execute(self._since(
            select(Dealer.name, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
            .join(Dealer, Dealer.id == Order.dealer_id).where(valid), Order.created_at, since)
            .group_by(Dealer.name).order_by(func.sum(Order.total_amount).desc()).limit(TOP))
        s.by_dealer = [(name, n, Decimal(total)) for name, n, total in dealer_rows.all()]

        part_rows = await self.session.execute(self._since(
            select(OrderItem.name_ru, OrderItem.part_number, func.sum(OrderItem.quantity))
            .join(Order, Order.id == OrderItem.order_id).where(valid), Order.created_at, since)
            .group_by(OrderItem.name_ru, OrderItem.part_number)
            .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.name_ru).limit(TOP))
        s.top_parts = [(name, number, int(qty)) for name, number, qty in part_rows.all()]

        s.new_clients = await self.session.scalar(self._since(
            select(func.count(User.id)).where(User.phone.is_not(None)), User.created_at, since))
        s.active_clients = await self.session.scalar(self._since(
            select(func.count(func.distinct(Order.user_id))), Order.created_at, since))
        return s

    async def orders_for_export(self, since: datetime | None) -> list[Order]:
        result = await self.session.scalars(self._since(select(Order), Order.created_at, since).order_by(Order.id))
        return list(result.unique())

    async def orders_page(self, since: datetime | None, offset: int, limit: int) -> tuple[list[Order], int]:
        """Заказы периода, новые сверху (с составом — order.items загружаются сразу)."""
        query = self._since(select(Order), Order.created_at, since)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))
        return list(result.unique()), total

    async def daily(self, since: datetime | None, until: datetime | None, tz: ZoneInfo) -> list[Day]:
        """Заказы и выручка по дням (по местному времени), без пропусков дней."""
        self.until = until
        rows = (await self.session.execute(self._since(
            select(Order.created_at, Order.total_amount, Order.status), Order.created_at, since))).all()
        if not rows and since is None:
            return []
        days: dict[date, Day] = {}
        for created, total, status in rows:
            created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            d = days.setdefault(created.astimezone(tz).date(), Day(created.astimezone(tz).date()))
            d.orders += 1
            if status != "CANCELLED":
                d.revenue += Decimal(total)
        first = since.astimezone(tz).date() if since is not None else min(days)
        last = ((until - timedelta(seconds=1)).astimezone(tz).date() if until is not None
                else datetime.now(timezone.utc).astimezone(tz).date())
        result, day = [], first
        while day <= last and len(result) < 400:  # не больше ~года столбиков
            result.append(days.get(day, Day(day)))
            day += timedelta(days=1)
        return result
