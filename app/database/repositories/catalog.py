"""Чтение каталога: модели → узлы → детали. Показываем только активные записи."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Node, Part


def _name_order(table, lang: str | None):
    """Сортировка по названию на языке пользователя (нет перевода — по русскому)."""
    column = getattr(table, f"name_{lang}", None) if lang in ("en", "uz") else None
    return func.coalesce(column, table.name_ru) if column is not None else table.name_ru


def _active_parts():
    return select(Part.id).where(Part.active.is_(True))


class CatalogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_models(self, lang: str | None) -> list[CarModel]:
        """Только модели, у которых есть хотя бы одна активная деталь."""
        has_parts = _active_parts().where(Part.model_id == CarModel.id).exists()
        result = await self.session.execute(
            select(CarModel).where(CarModel.active.is_(True), has_parts).order_by(_name_order(CarModel, lang))
        )
        return list(result.scalars())

    async def get_model(self, model_id: int) -> CarModel | None:
        return await self.session.scalar(
            select(CarModel).where(CarModel.id == model_id, CarModel.active.is_(True))
        )

    async def list_nodes(self, model_id: int, lang: str | None) -> list[Node]:
        """Узлы, в которых у этой модели есть активные детали."""
        has_parts = _active_parts().where(Part.node_id == Node.id, Part.model_id == model_id).exists()
        result = await self.session.execute(
            select(Node).where(Node.active.is_(True), has_parts).order_by(_name_order(Node, lang))
        )
        return list(result.scalars())

    async def get_node(self, node_id: int) -> Node | None:
        return await self.session.scalar(select(Node).where(Node.id == node_id, Node.active.is_(True)))

    async def count_parts(self, model_id: int, node_id: int) -> int:
        return await self.session.scalar(
            select(func.count(Part.id)).where(
                Part.model_id == model_id, Part.node_id == node_id, Part.active.is_(True)
            )
        )

    async def list_parts(
        self, model_id: int, node_id: int, lang: str | None, offset: int, limit: int
    ) -> list[Part]:
        result = await self.session.execute(
            select(Part)
            .where(Part.model_id == model_id, Part.node_id == node_id, Part.active.is_(True))
            .order_by(_name_order(Part, lang), Part.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars())

    async def get_part(self, part_id: int) -> Part | None:
        return await self.session.scalar(select(Part).where(Part.id == part_id, Part.active.is_(True)))
