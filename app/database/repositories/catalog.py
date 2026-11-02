"""Чтение каталога: модели → узлы → детали.

Показываем только детали, которые сейчас можно заказать в регионе пользователя:
  • есть в наличии (остаток > 0) у работающего дилера региона, или
  • есть на складе JAC (предзаказ), а в регионе есть дилер, к которому их привезут.
Модель или категория без таких деталей в списке не появляется."""
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Dealer, Node, Part, Region, Stock
from app.services.import_mapping import ALL_MODELS


def _name_order(table, lang: str | None):
    """Сортировка по названию на языке пользователя (нет перевода — по русскому)."""
    column = getattr(table, f"name_{lang}", None) if lang in ("en", "uz") else None
    return func.coalesce(column, table.name_ru) if column is not None else table.name_ru


def _offer(warehouse: bool):
    """Остаток детали у включённого дилера из последней выгрузки (warehouse — на складе JAC)."""
    return (select(Stock.id).join(Dealer, Dealer.id == Stock.dealer_id)
            .where(Stock.part_id == Part.id, Stock.quantity > 0, Dealer.active.is_(True), Dealer.enabled.is_(True),
                   Dealer.is_warehouse.is_(warehouse)))


def pickup_conditions():
    """Дилер, к которому можно привезти предзаказ: включён, не склад, есть в выгрузке или в справочнике."""
    return (Dealer.enabled.is_(True), Dealer.is_warehouse.is_(False),
            or_(Dealer.active.is_(True), Dealer.in_directory.is_(True)))


def _in_stock(region_id: int | None):
    """Деталь можно заказать: в наличии у дилера региона или на складе JAC (если в регионе есть дилер)."""
    warehouse = _offer(True).exists()
    if region_id is None:
        return or_(_offer(False).exists(), warehouse)
    local = _offer(False).where(Dealer.region_id == region_id).exists()
    pickup = select(Dealer.id).where(Dealer.region_id == region_id, *pickup_conditions()).exists()
    return or_(local, and_(warehouse, pickup))


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

    async def regions_with_stock(self, limit: int = 5) -> list[tuple[Region, int]]:
        """Регионы, где у дилеров есть детали в наличии, и сколько деталей — для подсказки сотрудникам."""
        parts = func.count(func.distinct(Stock.part_id))
        rows = await self.session.execute(
            select(Region, parts).join(Dealer, Dealer.region_id == Region.id).join(Stock, Stock.dealer_id == Dealer.id)
            .join(Part, Part.id == Stock.part_id)
            .where(Stock.quantity > 0, Dealer.active.is_(True), Dealer.enabled.is_(True), Part.active.is_(True),
                   Dealer.is_warehouse.is_(False))
            .group_by(Region.id).order_by(parts.desc(), Region.sort_order).limit(limit))
        return [(region, n) for region, n in rows.unique().all()]

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

    async def search(self, query: str, lang: str | None, models: set[str] | None = None,
                     mod: str | None = None, limit: int = 30) -> list[Part]:
        """Поиск по названию (на всех трёх языках) и артикулу среди деталей, которые можно заказать.
        models — только эти модели (клиенту: его автомобиль и «Прочее»); None — все.
        Сравниваем в Python: так «ФИЛЬТР» = «фильтр», «o‘» = «o'» и в PostgreSQL, и в тестах (SQLite)."""
        from app.services.search import matches, rank

        conditions = [*self._shown(), CarModel.active.is_(True), Node.active.is_(True), _fits(mod)]
        if models is not None:
            conditions.append(CarModel.name_ru.in_(models))
        rows = (await self.session.execute(
            select(Part.id, Part.name_ru, Part.name_en, Part.name_uz, Part.part_number)
            .join(CarModel, CarModel.id == Part.model_id).join(Node, Node.id == Part.node_id).where(*conditions)
        )).all()
        found = sorted((rank(query, r, lang), r.id) for r in rows if matches(query, r))[:limit]
        if not found:
            return []
        parts = {p.id: p for p in (await self.session.scalars(select(Part).where(Part.id.in_([i for _, i in found])))).unique()}
        return [parts[i] for _, i in found if i in parts]

    async def with_local_stock(self, part_ids: list[int]) -> set[int]:
        """Какие из деталей есть в наличии у дилеров региона (остальные — только под заказ со склада)."""
        if not part_ids or self.region_id is None:
            return set()
        local = _offer(False).where(Dealer.region_id == self.region_id).exists()
        return set(await self.session.scalars(select(Part.id).where(Part.id.in_(part_ids), local)))
