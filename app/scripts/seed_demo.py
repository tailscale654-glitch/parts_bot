"""Тестовый каталог, чтобы проверить бота до загрузки Excel (этап 4).

Добавить:  docker compose exec bot python -m app.scripts.seed_demo
Удалить:   docker compose exec bot python -m app.scripts.seed_demo --remove

Все демо-артикулы начинаются с DEMO-, поэтому их легко отличить и удалить.
Цены и артикулы НЕ настоящие.
"""
import asyncio
import sys

from sqlalchemy import delete, select

from app.config import _build_database_url
from app.database.database import create_engine, create_session_factory
from app.database.models import CarModel, Node, Part

MODELS = ["JAC JS2", "JAC JS4", "JAC J7", "JAC T8"]

NODES = {
    "engine": ("Двигатель", "Engine", "Dvigatel"),
    "gearbox": ("Коробка передач", "Gearbox", "Uzatmalar qutisi"),
    "suspension": ("Ходовая часть", "Suspension", "Yurish qismi"),
    "brakes": ("Тормозная система", "Brake system", "Tormoz tizimi"),
    "electrics": ("Электрика", "Electrics", "Elektr jihozlari"),
    "cooling": ("Система охлаждения", "Cooling system", "Sovutish tizimi"),
    "lighting": ("Освещение", "Lighting", "Yoritish"),
}

PARTS = {
    "engine": [
        ("Масляный фильтр", "Oil filter", "Moy filtri"),
        ("Воздушный фильтр", "Air filter", "Havo filtri"),
        ("Топливный фильтр", "Fuel filter", "Yoqilg‘i filtri"),
        ("Свечи зажигания", "Spark plugs", "O‘t oldirish shamlari"),
        ("Ремень ГРМ", "Timing belt", "GRM tasmasi"),
        ("Натяжитель ремня", "Belt tensioner", "Tasma tortgichi"),
        ("Водяной насос", "Water pump", "Suv nasosi"),
        ("Прокладка ГБЦ", "Cylinder head gasket", "Silindrlar kallagi qistirmasi"),
        ("Катушка зажигания", "Ignition coil", "O‘t oldirish g‘altagi"),
        ("Датчик кислорода", "Oxygen sensor", "Kislorod datchigi"),
        ("Опора двигателя", "Engine mount", None),  # нет узбекского → покажется русское
    ],
    "brakes": [
        ("Тормозные колодки передние", "Front brake pads", "Old tormoz kolodkalari"),
        ("Тормозные колодки задние", "Rear brake pads", "Orqa tormoz kolodkalari"),
        ("Тормозной диск передний", "Front brake disc", "Old tormoz diski"),
    ],
    "suspension": [
        ("Амортизатор передний", "Front shock absorber", "Old amortizator"),
        ("Шаровая опора", "Ball joint", "Sharovoy tayanch"),
    ],
    "cooling": [("Радиатор охлаждения", "Radiator", "Sovutish radiatori")],
    "lighting": [("Фара передняя левая", "Front left headlight", "Old chap fara")],
    "electrics": [("Аккумулятор", "Battery", "Akkumulyator")],
    "gearbox": [("Комплект сцепления", "Clutch kit", "Ilashish to‘plami")],
}


async def seed(session) -> int:
    nodes = {}
    for key, (ru, en, uz) in NODES.items():
        node = await session.scalar(select(Node).where(Node.name_ru == ru))
        nodes[key] = node or Node(name_ru=ru, name_en=en, name_uz=uz)
        session.add(nodes[key])
    added = 0
    for m_index, model_name in enumerate(MODELS, start=1):
        model = await session.scalar(select(CarModel).where(CarModel.name_ru == model_name))
        if model is None:
            model = CarModel(name_ru=model_name, name_en=model_name, name_uz=model_name)
            session.add(model)
        await session.flush()
        for key, items in PARTS.items():
            for p_index, (ru, en, uz) in enumerate(items, start=1):
                number = f"DEMO-{m_index}{list(PARTS).index(key):02d}{p_index:02d}"
                exists = await session.scalar(
                    select(Part.id).where(Part.model_id == model.id, Part.part_number == number)
                )
                if not exists:
                    session.add(Part(model=model, node=nodes[key], name_ru=ru, name_en=en, name_uz=uz,
                                     part_number=number, model_id=model.id))
                    added += 1
    await session.commit()
    return added


async def remove(session) -> int:
    result = await session.execute(delete(Part).where(Part.part_number.like("DEMO-%")))
    # модели и узлы без деталей тоже убираем
    await session.execute(delete(CarModel).where(~select(Part.id).where(Part.model_id == CarModel.id).exists()))
    await session.execute(delete(Node).where(~select(Part.id).where(Part.node_id == Node.id).exists()))
    await session.commit()
    return result.rowcount


async def main() -> None:
    engine = create_engine(_build_database_url())
    async with create_session_factory(engine)() as session:
        if "--remove" in sys.argv:
            print(f"Удалено демо-деталей: {await remove(session)}")
        else:
            print(f"Добавлено демо-деталей: {await seed(session)}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
