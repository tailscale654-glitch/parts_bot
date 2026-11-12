"""Правки детали администратором: модели, категория, «скрыть из бота», фото, описание.

Хранятся по артикулу (таблица part_overrides) и главнее данных CarSale / Excel — применяются
при каждой синхронизации. Категория, скрытие, фото и описание видны в боте сразу,
модели — после ближайшей синхронизации (сервис sync запускается сразу после сохранения).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotSetting, CarModel, Node, Part, PartOverride
from app.services import import_mapping as mapping
from app.services.part_catalog import SYNC_REQUEST_KEY, part_key


@dataclass
class Override:
    """Для импорта: что заменить в строках этой детали."""
    models: list[tuple[str, str, str]] = field(default_factory=list)
    node: tuple[str, str, str] | None = None
    hidden: bool = False
    photo: str | None = None
    description: dict = field(default_factory=lambda: {"ru": None, "en": None, "uz": None})


def categories() -> list[tuple[str, str, str]]:
    return list(dict.fromkeys([*mapping.CATEGORIES.values(), mapping.OTHER_CATEGORY]))


def category(name_ru: str | None) -> tuple[str, str, str] | None:
    return next((c for c in categories() if c[0] == name_ru), None) if name_ru else None


def model_triple(name: str) -> tuple[str, str, str]:
    return mapping.ALL_MODELS if name == mapping.ALL_MODELS[0] else (name, name, name)


async def model_choices(session: AsyncSession) -> list[str]:
    """Модели для выбора: из import_mapping.py и те, что уже есть в базе. «Прочее» — в конце."""
    names = set(mapping.MODEL_NAMES.values()) | set(await session.scalars(select(CarModel.name_ru)))
    names.discard(mapping.ALL_MODELS[0])
    return sorted(names) + [mapping.ALL_MODELS[0]]


async def get(session: AsyncSession, part_number: str) -> PartOverride | None:
    return await session.scalar(select(PartOverride).where(PartOverride.key == part_key(part_number)))


async def load(session: AsyncSession) -> dict[str, Override]:
    result: dict[str, Override] = {}
    for o in await session.scalars(select(PartOverride)):
        result[o.key] = Override(
            models=[model_triple(m) for m in o.model_list], node=category(o.node_ru), hidden=o.hidden,
            photo=o.photo, description={"ru": o.description_ru, "en": None, "uz": o.description_uz},
        )
    return result


def _request_sync(session: AsyncSession, flag: BotSetting | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if flag is None:
        session.add(BotSetting(key=SYNC_REQUEST_KEY, value=now))
    else:
        flag.value = now


async def _same_number(session: AsyncSession, part_number: str) -> list[Part]:
    return list((await session.scalars(
        select(Part).where(func.upper(Part.part_number) == part_number.upper()))).unique())


async def save(session: AsyncSession, part: Part, *, models: list[str], node_ru: str | None, hidden: bool,
               photo: str | None, description_ru: str | None, description_uz: str | None, by_id: int | None) -> str:
    """Сохранить правку и сразу применить то, что можно без синхронизации. → текст для админа."""
    choices = await model_choices(session)
    models = [m for m in dict.fromkeys(models) if m in choices]
    node = category(node_ru)
    photo = (photo or "").strip() or None
    if photo and not photo.startswith(("https://", "http://")):
        raise ValueError("Фото — ссылка, начинается с https://")
    item = await get(session, part.part_number)
    if item is None:
        item = PartOverride(key=part_key(part.part_number), part_number=part.part_number)
        session.add(item)
    models_changed = item.model_list != models
    unhidden = item.hidden and not hidden
    item.models, item.node_ru, item.hidden = "|".join(models), node[0] if node else None, hidden
    item.photo = photo
    item.description_ru = (description_ru or "").strip() or None
    item.description_uz = (description_uz or "").strip() or None
    item.updated_by = by_id

    # сразу в боте: категория, скрытие, фото, описание — у всех строк этого артикула (во всех моделях)
    node_row = None
    if node:
        node_row = await session.scalar(select(Node).where(Node.name_ru == node[0]))
        if node_row is None:
            node_row = Node(name_ru=node[0], name_en=node[1], name_uz=node[2])
            session.add(node_row)
            await session.flush()
        node_row.active = True
    for p in await _same_number(session, part.part_number):
        if node_row is not None:
            p.node_id = node_row.id
        if hidden:
            p.active = False
        if photo:
            p.photo = photo
        if item.description_ru:
            p.description_ru = item.description_ru
        if item.description_uz:
            p.description_uz = item.description_uz

    notes = []
    if models_changed or unhidden or not hidden:
        _request_sync(session, await session.get(BotSetting, SYNC_REQUEST_KEY))
        if models_changed or unhidden:
            notes.append("модели и показ в боте обновятся через 1–2 минуты (синхронизация с CarSale уже запущена)")
    if hidden:
        notes.append("деталь скрыта из бота")
    return "Сохранено" + (": " + "; ".join(notes) if notes else ". В боте — сразу.")


async def reset(session: AsyncSession, part: Part) -> bool:
    item = await get(session, part.part_number)
    if item is None:
        return False
    await session.delete(item)
    for p in await _same_number(session, part.part_number):  # фото и описание были только из правки
        p.photo, p.description_ru, p.description_uz = None, None, None
    _request_sync(session, await session.get(BotSetting, SYNC_REQUEST_KEY))
    return True
