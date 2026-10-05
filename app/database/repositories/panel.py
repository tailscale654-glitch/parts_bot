"""Запросы веб-панели: заказы, дилеры, клиенты, каталог — с фильтрами и поиском."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from decimal import Decimal

from sqlalchemy import String, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CarModel, Dealer, DealerStaff, Node, Order, OrderItem, OrderMessage, Part, PartOverride, PartTranslation, Region,
    Stock, User,
)
from app.database.repositories.admin import ORDER_FILTERS
from app.utils.names import part_name_key


def _like(q: str) -> str:
    return f"%{q.strip().lower()}%"


@dataclass
class DealerLine:
    dealer: Dealer
    offers: int  # позиций в наличии
    orders: int
    open_orders: int  # новые + в работе
    staff: int


@dataclass
class ClientLine:
    user: User
    orders: int
    spent: Decimal
    last_order_at: datetime | None


@dataclass
class PartLine:
    part: Part
    offers: int  # у скольких дилеров в наличии
    quantity: int  # всего штук
    min_price: Decimal | None


@dataclass
class PartOffer:
    stock: Stock
    reserved: int  # в незакрытых заказах


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

    # ---------- дилеры ----------

    async def dealer_lines(self, q: str = "", region_id: int | None = None, state: str = "") -> list[DealerLine]:
        offers = select(func.count(Stock.id)).where(Stock.dealer_id == Dealer.id, Stock.quantity > 0).scalar_subquery()
        orders = select(func.count(Order.id)).where(Order.dealer_id == Dealer.id).scalar_subquery()
        open_orders = select(func.count(Order.id)).where(
            Order.dealer_id == Dealer.id, Order.status.in_(("NEW", "CONFIRMED", "READY"))).scalar_subquery()
        staff = select(func.count(DealerStaff.id)).where(DealerStaff.dealer_id == Dealer.id).scalar_subquery()
        query = select(Dealer, offers, orders, open_orders, staff).join(Region, Region.id == Dealer.region_id)
        if q.strip():
            like = _like(q)
            query = query.where(or_(func.lower(Dealer.name).like(like), func.lower(func.coalesce(Dealer.code, "")).like(like),
                                    func.coalesce(Dealer.phone, "").like(like),
                                    func.lower(func.coalesce(Dealer.address, "")).like(like)))
        if region_id:
            query = query.where(Dealer.region_id == region_id)
        if state == "on":
            query = query.where(Dealer.enabled.is_(True), Dealer.active.is_(True))
        elif state == "off":
            query = query.where(or_(Dealer.enabled.is_(False), Dealer.active.is_(False)))
        result = await self.session.execute(query.order_by(Region.sort_order, Dealer.name))
        return [DealerLine(d, o or 0, n or 0, w or 0, st or 0) for d, o, n, w, st in result.unique().all()]

    # ---------- клиенты ----------

    async def client_lines(self, q: str = "", who: str = "", offset: int = 0, limit: int = 50,
                           user_id: int | None = None) -> tuple[list[ClientLine], int]:
        """who: "" — с телефоном (закончили регистрацию), all — все, blocked — заблокированные, buyers — с заказами."""
        orders = select(func.count(Order.id)).where(Order.user_id == User.id).scalar_subquery()
        spent = (select(func.coalesce(func.sum(Order.total_amount), 0))
                 .where(Order.user_id == User.id, Order.status != "CANCELLED").scalar_subquery())
        last = select(func.max(Order.created_at)).where(Order.user_id == User.id).scalar_subquery()
        query = select(User.id)
        if user_id is not None:
            query = query.where(User.id == user_id)
        if who == "blocked":
            query = query.where(User.blocked.is_(True))
        elif who == "buyers":
            query = query.where(select(Order.id).where(Order.user_id == User.id).exists())
        elif who != "all":
            query = query.where(User.phone.is_not(None))
        if q.strip():
            like = _like(q.lstrip("@"))
            conditions = [func.lower(func.coalesce(User.first_name, "")).like(like),
                          func.lower(func.coalesce(User.last_name, "")).like(like),
                          func.lower(func.coalesce(User.username, "")).like(like)]
            digits = "".join(ch for ch in q if ch.isdigit())
            if digits:
                conditions += [func.coalesce(User.phone, "").like(f"%{digits}%"),
                               func.cast(User.telegram_id, String).like(f"%{digits}%")]
            query = query.where(or_(*conditions))
        ids = query.subquery()
        total = await self.session.scalar(select(func.count()).select_from(ids))
        result = await self.session.execute(
            select(User, orders, spent, last).where(User.id.in_(select(ids.c.id)))
            .order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit))
        return [ClientLine(u, n or 0, Decimal(s or 0), t) for u, n, s, t in result.unique().all()], total

    async def set_blocked(self, user: User, blocked: bool) -> None:
        user.blocked = blocked
        await self.session.commit()

    # ---------- каталог ----------

    async def models(self) -> list[CarModel]:
        return list(await self.session.scalars(select(CarModel).order_by(CarModel.name_ru)))

    async def nodes(self) -> list[Node]:
        return list(await self.session.scalars(select(Node).order_by(Node.name_ru)))

    @staticmethod
    def untranslated_condition():
        """Нет перевода: узбекского нет или русское = английскому (так импорт пишет, когда перевода нет)."""
        return or_(Part.name_uz.is_(None), Part.name_uz == "", Part.name_ru == Part.name_en)

    async def part_lines(self, q: str = "", model_id: int | None = None, node_id: int | None = None,
                         show: str = "", offset: int = 0, limit: int = 50) -> tuple[list[PartLine], int]:
        """show: "" — в каталоге бота, hidden — скрытые (нет в последнем файле), untranslated — без перевода, all."""
        in_stock = (Stock.part_id == Part.id, Stock.quantity > 0)
        offers = select(func.count(Stock.id)).where(*in_stock).scalar_subquery()
        qty = select(func.coalesce(func.sum(Stock.quantity), 0)).where(*in_stock).scalar_subquery()
        min_price = select(func.min(Stock.price)).where(*in_stock).scalar_subquery()
        query = select(Part.id)
        if show == "hidden":
            query = query.where(Part.active.is_(False))
        elif show == "untranslated":
            query = query.where(Part.active.is_(True), self.untranslated_condition())
        elif show == "edited":  # изменены администратором в панели
            query = query.where(func.upper(Part.part_number).in_(select(PartOverride.key)))
        elif show != "all":
            query = query.where(Part.active.is_(True))
        if model_id:
            query = query.where(Part.model_id == model_id)
        if node_id:
            query = query.where(Part.node_id == node_id)
        if q.strip():
            like = _like(q)
            query = query.where(or_(func.lower(Part.part_number).like(like), func.lower(Part.name_ru).like(like),
                                    func.lower(func.coalesce(Part.name_uz, "")).like(like),
                                    func.lower(func.coalesce(Part.name_en, "")).like(like)))
        ids = query.subquery()
        total = await self.session.scalar(select(func.count()).select_from(ids))
        result = await self.session.execute(
            select(Part, offers, qty, min_price).where(Part.id.in_(select(ids.c.id)))
            .order_by(Part.name_ru, Part.part_number, Part.id).offset(offset).limit(limit))
        return [PartLine(p, o or 0, int(n or 0), m) for p, o, n, m in result.unique().all()], total

    async def untranslated_count(self) -> int:
        return await self.session.scalar(
            select(func.count(Part.id)).where(Part.active.is_(True), self.untranslated_condition())) or 0

    async def part_offers(self, part_id: int) -> list[PartOffer]:
        reserved = (
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.stock_id == Stock.id, Order.status.in_(("NEW", "CONFIRMED", "READY")))
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(Stock, reserved).join(Dealer, Dealer.id == Stock.dealer_id).join(Region, Region.id == Dealer.region_id)
            .where(Stock.part_id == part_id).order_by(Stock.quantity == 0, Region.sort_order, Stock.price))
        return [PartOffer(s, int(r or 0)) for s, r in result.unique().all()]

    async def same_name_parts(self, part: Part) -> int:
        """Сколько деталей (включая эту) получат перевод — у всех одинаковое английское название."""
        return len(await self._parts_named(part.name_en)) if part.name_en else 1

    async def _parts_named(self, english: str) -> list[int]:
        key = part_name_key(english)
        rows = await self.session.execute(select(Part.id, Part.name_en).where(Part.name_en.is_not(None)))
        return [pid for pid, name in rows.all() if part_name_key(name) == key]

    async def translation_for(self, part: Part) -> PartTranslation | None:
        if not part.name_en:
            return None
        return await self.session.scalar(select(PartTranslation).where(PartTranslation.key == part_name_key(part.name_en)))

    async def save_translation(self, part: Part, name_ru: str, name_uz: str, by: User) -> int:
        """Сохранить перевод. Есть английское название → запоминаем его (переживёт новые загрузки)
        и меняем все детали с тем же названием. Нет → меняем только эту деталь. → сколько деталей изменено."""
        name_ru, name_uz = name_ru.strip()[:255], name_uz.strip()[:255]
        if not part.name_en:
            part.name_ru = name_ru or part.name_ru
            part.name_uz = name_uz or None
            await self.session.commit()
            return 1
        key = part_name_key(part.name_en)
        tr = await self.session.scalar(select(PartTranslation).where(PartTranslation.key == key))
        if tr is None:
            tr = PartTranslation(key=key, name_en=part.name_en)
            self.session.add(tr)
        tr.name_ru, tr.name_uz, tr.updated_by = name_ru or None, name_uz or None, by.id
        ids = await self._parts_named(part.name_en)
        # Пусто в поле «русский» = показывать английское название (как без перевода)
        await self.session.execute(
            update(Part).where(Part.id.in_(ids))
            .values(name_ru=func.coalesce(name_ru or None, Part.name_en), name_uz=name_uz or None)
            .execution_options(synchronize_session="fetch"))
        await self.session.commit()
        await self.session.refresh(part)
        return len(ids)
