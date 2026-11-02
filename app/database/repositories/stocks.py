"""Предложения дилеров: цена и остаток детали. Склад JAC — отдельно (предзаказ)."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, Stock
from app.database.repositories.catalog import pickup_conditions


class StockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def offers_in_region(self, part_id: int, region_id: int | None) -> list[Stock]:
        """Дилеры региона: сначала в наличии, среди них — дешевле выше; потом «нет в наличии»."""
        result = await self.session.scalars(
            select(Stock)
            .join(Dealer, Dealer.id == Stock.dealer_id)
            .where(Stock.part_id == part_id, Dealer.region_id == region_id, Dealer.is_warehouse.is_(False),
                   Dealer.active.is_(True), Dealer.enabled.is_(True))
            .order_by((Stock.quantity > 0).desc(), Stock.price, Dealer.name)
        )
        return list(result.unique())

    async def regions_elsewhere(self, part_id: int, region_id: int | None) -> int:
        """В скольких ДРУГИХ регионах деталь есть в наличии у дилеров."""
        return await self.session.scalar(
            select(func.count(func.distinct(Dealer.region_id)))
            .select_from(Stock)
            .join(Dealer, Dealer.id == Stock.dealer_id)
            .where(Stock.part_id == part_id, Stock.quantity > 0, Dealer.active.is_(True), Dealer.is_warehouse.is_(False),
                   Dealer.enabled.is_(True), Dealer.region_id != region_id)
        )

    async def warehouse_offer(self, part_id: int) -> Stock | None:
        """Деталь на складе JAC (для предзаказа): дешевле и больше штук — выше."""
        return (await self.session.scalars(
            select(Stock)
            .join(Dealer, Dealer.id == Stock.dealer_id)
            .where(Stock.part_id == part_id, Stock.quantity > 0, Dealer.is_warehouse.is_(True),
                   Dealer.active.is_(True), Dealer.enabled.is_(True))
            .order_by(Stock.price, Stock.quantity.desc(), Stock.id)
            .limit(1)
        )).unique().one_or_none()

    async def pickup_dealers(self, region_id: int | None) -> list[Dealer]:
        """Дилеры региона, у которых можно забрать предзаказ."""
        if region_id is None:
            return []
        result = await self.session.scalars(
            select(Dealer).where(Dealer.region_id == region_id, *pickup_conditions()).order_by(Dealer.name))
        return list(result.unique())

    async def price_info(self, part_ids: list[int], region_id: int | None) -> dict[int, dict]:
        """Для списка деталей: лучшая цена и число дилеров с наличием в регионе, цена на складе JAC.
        → {part_id: {"local": цена | None, "dealers": n, "warehouse": цена | None}}."""
        info = {pid: {"local": None, "dealers": 0, "warehouse": None} for pid in part_ids}
        if not part_ids:
            return info
        base = (Stock.part_id.in_(part_ids), Stock.quantity > 0, Dealer.active.is_(True), Dealer.enabled.is_(True))
        local = await self.session.execute(
            select(Stock.part_id, func.min(Stock.price), func.count(Stock.id)).join(Dealer, Dealer.id == Stock.dealer_id)
            .where(*base, Dealer.is_warehouse.is_(False), Dealer.region_id == region_id).group_by(Stock.part_id))
        for pid, price, n in local.all():
            info[pid].update(local=price, dealers=n)
        if await self.pickup_dealers(region_id):  # предзаказ — только если в регионе есть дилер выдачи
            warehouse = await self.session.execute(
                select(Stock.part_id, func.min(Stock.price)).join(Dealer, Dealer.id == Stock.dealer_id)
                .where(*base, Dealer.is_warehouse.is_(True)).group_by(Stock.part_id))
            for pid, price in warehouse.all():
                info[pid]["warehouse"] = price
        return info

    async def get(self, stock_id: int) -> Stock | None:
        return await self.session.get(Stock, stock_id)

    async def get_dealer(self, dealer_id: int) -> Dealer | None:
        return await self.session.get(Dealer, dealer_id)
