"""Справочник запчастей завода: файлы «MODEL / SN / part code / Spare part name».

В таких файлах нет остатков, цен и дилеров — только какая деталь к какой модели подходит.
Бот использует справочник при каждой загрузке остатков (из CarSale или Excel): если у детали
модель не указана («—»), модель берётся отсюда, и деталь показывается в своей модели,
а не в «Прочее».

Файлы дополняют друг друга: загрузка нового списка ничего не удаляет, а модели одного артикула
из разных файлов объединяются.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotSetting, PartCatalog
from app.services import import_mapping as mapping

SYNC_REQUEST_KEY = "carsale_sync_request"  # «синхронизировать сейчас» — сервис sync проверяет каждые 20 с
HEADER_ROWS = 10  # строка заголовков ищется в первых строках листа
BRACKETS = str.maketrans({"（": "(", "）": ")", "，": ",", "：": ":"})


@dataclass
class CatalogRow:
    part_number: str
    models: list[str]  # коды моделей: ["T9-P33Z3", "T8-P30BF"]
    name_en: str | None
    row: int = 0


@dataclass
class CatalogStats:
    total: int = 0       # артикулов в файле
    new: int = 0         # новых в справочнике
    updated: int = 0     # уже были (модели дополнены)
    models: str = ""     # «JAC M4 Luxe: 646, JAC M3: 606…»
    in_bot: int = 0      # деталей в боте без модели, которые теперь получат модель
    catalog_total: int = 0


def part_key(number: str) -> str:
    return re.sub(r"\s+", "", str(number)).upper()


def _clean(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = " ".join(str(value).translate(BRACKETS).split())
    return text or None


def _column(columns: list[str], *tests) -> int | None:
    for i, name in enumerate(columns):
        low = name.lower()
        if any(t(low) for t in tests):
            return i
    return None


def find_header(df: pd.DataFrame) -> tuple[int, int, int, int] | None:
    """→ (строка заголовков, колонка модели, колонка артикула, колонка названия) или None."""
    for i in range(min(HEADER_ROWS, len(df))):
        cells = [(_clean(v) or "") for v in df.iloc[i].tolist()]
        model = _column(cells, lambda s: s == "model")
        code = _column(cells, lambda s: "code" in s and "part" in s)
        name = _column(cells, lambda s: "name" in s and s != "model", lambda s: s.startswith("description"))
        if None not in (model, code, name):
            return i, model, code, name
    return None


def _read_sheets(path: Path) -> dict[str, pd.DataFrame]:
    try:
        return pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="openpyxl")
    except Exception:
        return {}


def is_catalog(path: Path) -> bool:
    try:
        book = pd.read_excel(path, sheet_name=None, header=None, nrows=HEADER_ROWS, dtype=str, engine="openpyxl")
    except Exception:
        return False
    return any(find_header(df) for df in book.values())


_CODES = {code.upper(): code for code in mapping.MODEL_NAMES}


def model_codes(raw: str | None) -> list[str]:
    """«T9-P33Z3,T8-P30BF» → два кода; «RF8-V9AA3,V9HA0» → RF8-V9AA3, RF8-V9HA0; «SUNRAY» → «Sunray»."""
    codes, prefix = [], ""
    for token in (t.strip() for t in (raw or "").split(",")):
        if not token:
            continue
        if token.upper() in _CODES:
            token = _CODES[token.upper()]
        elif "-" not in token and prefix:
            token = prefix + token  # продолжение списка без префикса
        if "-" in token:
            prefix = token.split("-", 1)[0] + "-"
        if token not in codes:
            codes.append(token)
    return codes


def _strip_model(name: str | None, codes: list[str]) -> str | None:
    """«BARE ENGINE Sunray» → «BARE ENGINE»: в одном из файлов модель дописана к названию."""
    if not name:
        return name
    for code in codes:
        if name.upper().endswith(" " + code.upper()):
            return name[: -len(code) - 1].strip() or name
    return name


def validate_catalog(path: Path):
    """→ (строки, ошибки, предупреждения). Используются ImportError_ из excel_import (ключи переводов)."""
    from app.services.excel_import import ImportError_

    rows: dict[str, CatalogRow] = {}
    warnings: list = []
    unknown: set[str] = set()
    no_model = 0
    for df in _read_sheets(path).values():
        found = find_header(df)
        if not found:
            continue
        header, mi, ci, ni = found
        for i in range(header + 1, len(df)):
            values = df.iloc[i].tolist()
            number = _clean(values[ci])
            if not number:
                continue
            codes = model_codes(_clean(values[mi]))
            if not codes:
                no_model += 1
                continue
            unknown.update(c for c in codes if c not in mapping.MODEL_NAMES)
            name = _strip_model(_clean(values[ni]), codes)
            key = part_key(number)
            row = rows.get(key)
            if row is None:
                rows[key] = CatalogRow(number[:64], codes, name[:255] if name else None, i + 1)
            else:  # один артикул в нескольких строках (разные модели) — объединяем
                row.models += [c for c in codes if c not in row.models]
                row.name_en = row.name_en or name
    if no_model:
        warnings.append(ImportError_(0, "warn_catalog_no_model", {"n": no_model}))
    if unknown:
        warnings.append(ImportError_(0, "warn_unknown_models", {"models": ", ".join(sorted(unknown))}))
    errors = [] if rows else [ImportError_(0, "err_no_rows")]
    return list(rows.values()), errors, warnings


def model_title(code: str) -> str:
    return mapping.MODEL_NAMES.get(code, code)


async def load(session: AsyncSession) -> dict[str, str]:
    """Справочник для импорта остатков: ключ артикула → «M4,M3»."""
    rows = await session.execute(select(PartCatalog.key, PartCatalog.models))
    return dict(rows.all())


async def apply_catalog(session: AsyncSession, rows: list[CatalogRow]) -> CatalogStats:
    """Дополнить справочник и попросить сервис sync сразу обновить остатки (модели подтянутся)."""
    from app.database.models import CarModel, Part

    stats = CatalogStats(total=len(rows))
    existing = {c.key: c for c in await session.scalars(select(PartCatalog))}
    per_model: dict[str, int] = {}
    for r in rows:
        key = part_key(r.part_number)
        item = existing.get(key)
        if item is None:
            item = existing[key] = PartCatalog(key=key, part_number=r.part_number, models=",".join(r.models),
                                               name_en=r.name_en)
            session.add(item)
            stats.new += 1
        else:
            have = model_codes(item.models)
            merged = have + [c for c in r.models if c not in have]
            item.models = ",".join(merged)[:255]
            item.name_en = item.name_en or r.name_en
            stats.updated += 1
        for title in dict.fromkeys(model_title(c) for c in r.models):
            per_model[title] = per_model.get(title, 0) + 1
    await session.flush()
    stats.models = ", ".join(f"{m}: {n}" for m, n in sorted(per_model.items(), key=lambda kv: -kv[1]))
    stats.catalog_total = len(existing)

    no_model = await session.scalars(
        select(Part.part_number).join(CarModel, CarModel.id == Part.model_id)
        .where(Part.active.is_(True), CarModel.name_ru == mapping.ALL_MODELS[0]))
    stats.in_bot = len({part_key(n) for n in no_model} & set(existing))

    if stats.in_bot:  # модели в боте обновятся при ближайшей синхронизации — просим запустить её сейчас
        flag = await session.get(BotSetting, SYNC_REQUEST_KEY)
        now = datetime.now(timezone.utc).isoformat()
        if flag is None:
            session.add(BotSetting(key=SYNC_REQUEST_KEY, value=now))
        else:
            flag.value = now
    return stats
