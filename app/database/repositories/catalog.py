"""Чтение каталога: модели → узлы → детали.

Показываем только детали, которые сейчас есть в наличии (остаток > 0) у работающего дилера региона
пользователя (заказать можно только там) — у клиентов, администраторов и сотрудников одинаково.
Модель или категория без таких деталей в списке не появляется."""
from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Dealer, Node, Part, Stock
from app.services.import_mapping import ALL_MODELS


def _name_order(table, lang: str | None):
    """Сортировка по названию на языке пользователя (нет перевода — по русскому)."""
    column = getattr(table, f"name_{lang}", None) if lang in ("en", "uz") else None
    return func.coalesce(column, table.name_ru) if column is not None else table.name_ru


def _in_stock(region_id: int | None):
    """У детали есть остаток у включённого дилера (из последней выгрузки) — в регионе или у любого."""
    offer = (select(Stock.id).join(Dealer, Dealer.id == Stock.dealer_id)
             .where(Stock.part_id == Part.id, Stock.quantity > 0, Dealer.active.is_(True), Dealer.enabled.is_(True)))
    if region_id is not None:
        offer = offer.where(Dealer.region_id == region_id)
    return offer.exists()


def _fits(mod: str | None):
    """Деталь подходит к модификации клиента: без указания модификаций или с этой в списке."""
    if not mod:
        return true()
    return or_(Part.mod_codes == "", Part.mod_codes.like(f"%{mod}%"))


class CatalogRepository:
    def __init__(self, session: AsyncSession, region_id: int | None = None):
        """region_id — показывать детали в наличии у дилеров этого региона; None — у любого дилера."""
        self.session = session
        self.region_id = region_id

    def _shown(self):
        return Part.active.is_(True), _in_stock(self.region_id)

    def _active_parts(self):
        return select(Part.id).where(*self._shown())

    async def list_models(self, lang: str | None) -> list[CarModel]:
        """Только модели, у которых есть хотя бы одна активная деталь."""
        has_parts = self._active_parts().where(Part.model_id == CarModel.id).exists()
        result = await self.session.execute(
            select(CarModel).where(CarModel.active.is_(True), has_parts).order_by(CarModel.name_ru == ALL_MODELS[0], _name_order(CarModel, lang))  # «Прочее» — в конце
        )
        return list(result.scalars())

    async def model_by_name(self, name_ru: str | None) -> CarModel | None:
        if not name_ru:
            return None
        return await self.session.scalar(
            select(CarModel).where(CarModel.name_ru == name_ru, CarModel.active.is_(True)))

    async def get_model(self, model_id: int) -> CarModel | None:
        return await self.session.scalar(
            select(CarModel).where(CarModel.id == model_id, CarModel.active.is_(True))
        )

    async def list_nodes(self, model_id: int, lang: str | None, mod: str | None = None) -> list[Node]:
        """Узлы, в которых у этой модели есть активные детали."""
        has_parts = self._active_parts().where(Part.node_id == Node.id, Part.model_id == model_id, _fits(mod)).exists()
        result = await self.session.execute(
            select(Node).where(Node.active.is_(True), has_parts).order_by(_name_order(Node, lang))
        )
        return list(result.scalars())

    async def get_node(self, node_id: int) -> Node | None:
        return await self.session.scalar(select(Node).where(Node.id == node_id, Node.active.is_(True)))

    async def count_parts(self, model_id: int, node_id: int, mod: str | None = None) -> int:
        return await self.session.scalar(
            select(func.count(Part.id)).where(
                Part.model_id == model_id, Part.node_id == node_id, *self._shown(), _fits(mod)
            )
        )

    async def list_parts(
        self, model_id: int, node_id: int, lang: str | None, offset: int, limit: int, mod: str | None = None
    ) -> list[Part]:
        result = await self.session.execute(
            select(Part)
            .where(Part.model_id == model_id, Part.node_id == node_id, *self._shown(), _fits(mod))
            .order_by(_name_order(Part, lang), Part.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars())

    async def get_part(self, part_id: int) -> Part | None:
        return await self.session.scalar(select(Part).where(Part.id == part_id, Part.active.is_(True)))

    async def count_parts_by_node(self, model_id: int) -> dict[int, int]:
        result = await self.session.execute(
            select(Part.node_id, func.count(Part.id))
            .where(Part.model_id == model_id, *self._shown())
            .group_by(Part.node_id)
        )
        return dict(result.all())

    async def search_parts(self, query: str, lang: str | None, limit: int = 30) -> list[Part]:
        """Поиск по названию (на всех трёх языках) и по артикулу."""
        pattern = f"%{query}%"
        result = await self.session.execute(
            select(Part)
            .join(CarModel, CarModel.id == Part.model_id)
            .join(Node, Node.id == Part.node_id)
            .where(
                Part.active.is_(True),
                CarModel.active.is_(True),
                Node.active.is_(True),
                or_(
                    Part.name_ru.ilike(pattern),
                    Part.name_en.ilike(pattern),
                    Part.name_uz.ilike(pattern),
                    Part.part_number.ilike(pattern),
                ),
            )
            .order_by(_name_order(Part, lang), Part.id)
            .limit(limit)
        )
        return list(result.scalars())
