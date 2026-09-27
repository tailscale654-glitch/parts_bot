"""Работа с таблицей regions."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Region


class RegionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[Region]:
        result = await self.session.execute(
            select(Region).where(Region.active.is_(True)).order_by(Region.sort_order, Region.id)
        )
        return list(result.scalars())

    async def get_active(self, region_id: int) -> Region | None:
        result = await self.session.execute(
            select(Region).where(Region.id == region_id, Region.active.is_(True))
        )
        return result.scalar_one_or_none()
