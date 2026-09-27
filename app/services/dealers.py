"""Справочник дилеров: сопоставление названий и загрузка файла «Название / Код / Адрес / Район / Телефон / Статус».

В складской выгрузке и в справочнике один и тот же дилер записан по-разному:
  «OOO «ASIAMOTOR»»  и  «"Asia Motor" MChJ»
Поэтому сравниваем «ключ» названия: без ООО/MChJ/LLC/ИП, кавычек, пробелов и дефисов → «asiamotor».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, Region
from app.utils.names import dealer_key

DIRECTORY_COLUMNS = {"Название", "Район", "Статус"}
ACTIVE_STATUS = "Активный"


def _region_key(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"^(город|г\.|республика|respublikasi)\s*", "", text.strip())
    text = re.sub(r"\s*(respublikasi)$", "", text)
    return re.sub(r"\s+", " ", text)


def region_lookup(regions: list[Region]) -> dict[str, int]:
    """«город Ташкент», «Ташкент», «Tashkent», «tashkent_city», «Республика Каракалпакстан» → id региона."""
    lookup: dict[str, int] = {}
    for r in regions:
        for name in (r.code, r.name_ru, r.name_en, r.name_uz):
            if name:
                lookup[_region_key(name)] = r.id
    return lookup


def find_region(text: str | None, lookup: dict[str, int]) -> int | None:
    return lookup.get(_region_key(text)) if text else None


# ---------- файл-справочник ----------

@dataclass
class DirectoryRow:
    row: int
    name: str
    key: str
    code: str | None
    address: str | None
    phone: str | None
    region_id: int
    enabled: bool


@dataclass
class DirectoryStats:
    total: int = 0
    new: int = 0
    updated: int = 0
    disabled: int = 0
    regions: int = 0


def _clean(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return None if text in ("", "-", "—") else text


def is_directory(path: Path) -> bool:
    try:
        header = pd.read_excel(path, nrows=0, engine="openpyxl").columns
    except Exception:
        return False
    return DIRECTORY_COLUMNS <= {str(c).strip() for c in header}


def validate_directory(path: Path, regions: list[Region]):
    """→ (строки, ошибки). Ошибки в формате ImportError_ (импортируем внутри, чтобы не было цикла)."""
    from app.services.excel_import import ImportError_

    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    lookup = region_lookup(regions)
    rows, errors, seen = [], [], {}
    for index, raw in df.iterrows():
        excel_row = int(index) + 2
        name = _clean(raw.get("Название"))
        if not name:
            continue
        region_text = _clean(raw.get("Район"))
        region_id = find_region(region_text, lookup)
        if region_id is None:
            errors.append(ImportError_(excel_row, "err_region", {"value": region_text or "—"}))
            continue
        key = dealer_key(name)
        if key in seen:
            errors.append(ImportError_(excel_row, "err_duplicate_dealer", {"other": seen[key]}))
            continue
        seen[key] = excel_row
        rows.append(DirectoryRow(
            row=excel_row, name=name[:255], key=key, code=_clean(raw.get("Код")),
            address=(_clean(raw.get("Адрес")) or "")[:512] or None,
            phone=(_clean(raw.get("Номер телефона")) or "")[:32] or None,
            region_id=region_id, enabled=_clean(raw.get("Статус")) == ACTIVE_STATUS,
        ))
    if not rows and not errors:
        errors.append(ImportError_(0, "err_no_rows"))
    return rows, errors


async def apply_directory(session: AsyncSession, rows: list[DirectoryRow]) -> DirectoryStats:
    """Создаёт/обновляет дилеров. Дилеров, которых нет в справочнике, не трогает."""
    stats = DirectoryStats(total=len(rows), regions=len({r.region_id for r in rows}))
    existing = {d.name_key: d for d in (await session.scalars(select(Dealer))).unique()}
    for r in rows:
        dealer = existing.get(r.key)
        if dealer is None:
            dealer = existing[r.key] = Dealer(name_key=r.key, active=False)  # цен ещё нет — появятся с выгрузкой
            session.add(dealer)
            stats.new += 1
        else:
            stats.updated += 1
        dealer.name = r.name
        dealer.code = r.code
        dealer.region_id = r.region_id
        dealer.address = r.address
        dealer.phone = r.phone
        dealer.enabled = r.enabled
        dealer.in_directory = True
        stats.disabled += not r.enabled
    await session.flush()
    return stats
