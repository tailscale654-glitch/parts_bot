import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from decimal import Decimal

from sqlalchemy import select

from app.database.models import Base, CarModel, Dealer, Node, Part, Region, Stock
from app.database.repositories.catalog import CatalogRepository
from app.keyboards.catalog import CatalogCB, parts_keyboard
from app.scripts.seed_demo import remove, seed
from app.services.catalog import paginate, part_card_text


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        yield s
    await engine.dispose()


async def stock_everything(session, qty: int = 2) -> Dealer:
    """Демо-детали без остатков; каталог показывает только то, что есть у дилера, — даём остаток."""
    dealer = Dealer(region=Region(code="tashkent_city", name_ru="Ташкент"), name="JAC Ташкент")
    for part in (await session.scalars(select(Part))).unique():
        session.add(Stock(part=part, dealer=dealer, price=Decimal(1000), quantity=qty))
    await session.commit()
    return dealer


@pytest.mark.parametrize("total,req,expected", [(0, 1, (1, 1)), (20, 1, (1, 3)), (20, 3, (3, 3)), (20, 99, (3, 3)), (20, -5, (1, 3))])
def test_paginate(total, req, expected):
    page = paginate(total, req, page_size=8)
    assert (page.number, page.total_pages) == expected


async def test_seed_is_idempotent_and_removable(session):
    first = await seed(session)
    assert first > 0
    assert await seed(session) == 0  # повторный запуск ничего не дублирует
    assert await remove(session) == first
    assert await CatalogRepository(session).list_models("ru") == []


async def test_catalog_navigation_and_filters(session):
    await seed(session)
    await stock_everything(session)
    repo = CatalogRepository(session)
    models = await repo.list_models("ru")
    assert [m.name_ru for m in models] == ["JAC J7", "JAC JS2", "JAC JS4", "JAC T8"]

    js4 = next(m for m in models if m.name_ru == "JAC JS4")
    nodes = await repo.list_nodes(js4.id, "en")
    assert "Engine" in [n.name_en for n in nodes]
    engine = next(n for n in nodes if n.name_en == "Engine")

    assert await repo.count_parts(js4.id, engine.id) == 11
    page2 = await repo.list_parts(js4.id, engine.id, "ru", offset=8, limit=8)
    assert len(page2) == 3


async def test_inactive_items_hidden(session):
    await seed(session)
    await stock_everything(session)
    repo = CatalogRepository(session)
    model = (await repo.list_models("ru"))[0]
    for part in (await session.execute(Part.__table__.select().where(Part.model_id == model.id))).all():
        obj = await session.get(Part, part.id)
        obj.active = False
    await session.commit()
    assert model.id not in [m.id for m in await repo.list_models("ru")]  # модель без активных деталей скрыта
    assert await repo.get_part(obj.id) is None


async def test_part_card_localized_with_fallback(session):
    model = CarModel(name_ru="JAC JS4", name_en="JAC JS4", name_uz="JAC JS4")
    node = Node(name_ru="Двигатель", name_en="Engine", name_uz="Dvigatel")
    part = Part(model=model, node=node, name_ru="Опора двигателя", name_en="Engine mount", name_uz=None, part_number="101001")
    session.add(part)
    await session.commit()
    uz = part_card_text(part, "uz")
    assert "ОПОРА ДВИГАТЕЛЯ" in uz and "Kategoriya: Dvigatel" in uz and "Artikul: 101001" in uz
    en = part_card_text(part, "en")
    assert "ENGINE MOUNT" in en and "Category: Engine" in en


def test_callback_data_fits_telegram_limit():
    data = CatalogCB(action="parts", model_id=99999, node_id=99999, part_id=9999999, page=999).pack()
    assert len(data.encode()) <= 64


def test_pagination_buttons():  # noqa
    parts = []
    kb = parts_keyboard(1, 2, parts, paginate(20, 2), "ru")
    nav = kb.inline_keyboard[0]
    assert [b.text for b in nav] == ["◀️", "2 / 3", "▶️"]
    assert CatalogCB.unpack(nav[2].callback_data).page == 3


def test_duplicate_names_get_part_number():
    parts = [Part(id=1, name_ru="FILTER", part_number="A1"), Part(id=2, name_ru="FILTER", part_number="B2"),
             Part(id=3, name_ru="BELT", part_number="C3")]
    kb = parts_keyboard(1, 2, parts, paginate(3, 1), "ru")
    assert [row[0].text for row in kb.inline_keyboard[:3]] == ["FILTER · A1", "FILTER · B2", "BELT"]


async def test_only_parts_in_stock_are_listed(session):
    """Нет остатка у дилера — детали нет в списке; клиенту — только у дилеров его региона."""
    tash, sam = Region(code="tashkent_city", name_ru="Ташкент"), Region(code="samarkand", name_ru="Самарканд")
    model, node = CarModel(name_ru="JAC T9"), Node(name_ru="Кузов")
    in_tash = Part(model=model, node=node, name_ru="Бампер", part_number="A1")
    sold_out = Part(model=model, node=node, name_ru="Фара", part_number="A2")
    closed_dealer = Part(model=model, node=node, name_ru="Зеркало", part_number="A3")
    only_sam = Part(model=model, node=node, name_ru="Решётка", part_number="A4")
    d_tash, d_sam = Dealer(region=tash, name="Т"), Dealer(region=sam, name="С")
    d_off = Dealer(region=tash, name="Выключен", enabled=False)
    session.add_all([
        Stock(part=in_tash, dealer=d_tash, price=Decimal(1), quantity=3),
        Stock(part=sold_out, dealer=d_tash, price=Decimal(1), quantity=0),  # всё продано / в заказах
        Stock(part=closed_dealer, dealer=d_off, price=Decimal(1), quantity=5),
        Stock(part=only_sam, dealer=d_sam, price=Decimal(1), quantity=1),
    ])
    await session.commit()

    client = CatalogRepository(session, tash.id)
    assert [p.name_ru for p in await client.list_parts(model.id, node.id, "ru", 0, 50)] == ["Бампер"]
    assert await client.count_parts(model.id, node.id) == 1
    anyone = CatalogRepository(session)  # администратор / сотрудник дилера — у любого дилера
    assert {p.name_ru for p in await anyone.list_parts(model.id, node.id, "ru", 0, 50)} == {"Бампер", "Решётка"}

    stock = await session.scalar(select(Stock).where(Stock.part_id == in_tash.id))
    stock.quantity = 0
    await session.commit()
    assert await client.list_models("ru") == [] and await client.list_nodes(model.id, "ru") == []
