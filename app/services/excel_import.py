"""Импорт каталога из Excel.

Два шага:
1. validate_file() — читает файл и проверяет каждую строку. База НЕ трогается.
2. apply_import()  — записывает данные в базу. Вызывается внутри транзакции:
   если что-то пошло не так, все изменения откатываются (rollback).

Файл считается ПОЛНЫМ прайсом: детали и цены, которых нет в файле, скрываются.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CarModel, Dealer, Node, Order, OrderItem, Part, Region, Stock
from app.services import import_mapping as mapping
from app.services.part_names import has_translation, translate
from app.services.dealers import dealer_key, find_region, is_directory, region_lookup, validate_directory

# Файлы из веб-систем часто без стилей — openpyxl об этом предупреждает, это не ошибка
warnings.filterwarnings("ignore", message="Workbook contains no default style")

MAX_FILE_MB = 10
MAX_ROWS = 50_000
MAX_ERRORS = 500  # дальше не проверяем — файл явно нужно исправлять целиком
SHEET_NAME = "parts"

REQUIRED = ["region", "dealer", "model_ru", "node_ru", "part_name_ru", "part_number", "price", "stock"]
OPTIONAL = [
    "model_en", "model_uz", "node_en", "node_uz", "part_name_en", "part_name_uz",
    "delivery_days", "description_ru", "description_en", "description_uz", "photo",
]
COLUMN_LIMITS = {  # максимальная длина текста — как в базе
    "dealer": 255, "model_ru": 128, "model_en": 128, "model_uz": 128,
    "node_ru": 128, "node_en": 128, "node_uz": 128,
    "part_name_ru": 255, "part_name_en": 255, "part_name_uz": 255,
    "part_number": 64, "photo": 512,
}


@dataclass
class ImportError_:
    row: int  # номер строки в Excel (0 = ошибка всего файла)
    key: str  # ключ перевода, например "err_price"
    params: dict = field(default_factory=dict)


@dataclass
class ImportRow:
    row: int
    region_id: int
    dealer: str
    model: dict  # {"ru": ..., "en": ..., "uz": ...}
    node: dict
    part_name: dict
    part_number: str
    price: Decimal
    stock: int
    delivery_days: int | None
    description: dict
    photo: str | None


@dataclass
class ImportStats:
    models: int = 0
    nodes: int = 0
    parts: int = 0
    dealers: int = 0
    regions: int = 0
    new: int = 0
    updated: int = 0
    hidden: int = 0
    reserved: int = 0  # штук вычтено из остатков: они в незакрытых заказах бота


# ---------- чтение и проверка ----------

def _clean(value) -> str | None:
    """Ячейка Excel → аккуратная строка или None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.endswith(".0") and text[:-2].isdigit():  # 101001.0 → 101001 (Excel хранит числа как float)
        text = text[:-2]
    return text or None


def _to_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(text.replace(" ", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def _to_int(text: str | None) -> int | None:
    value = _to_decimal(text)
    if value is None or value != value.to_integral_value():
        return None
    return int(value)


def read_excel(path: Path) -> pd.DataFrame:
    """Лист parts (или первый лист). Все ячейки читаем как текст — чтобы артикул 00123 не стал 123."""
    sheets = pd.ExcelFile(path, engine="openpyxl").sheet_names
    sheet = SHEET_NAME if SHEET_NAME in sheets else sheets[0]
    df = pd.read_excel(path, sheet_name=sheet, dtype=str, engine="openpyxl")
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def validate_file(path: Path, regions: list[Region]) -> tuple[list[ImportRow], list[ImportError_]]:
    try:
        df = read_excel(path)
    except Exception:
        return [], [ImportError_(0, "err_unreadable")]

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return [], [ImportError_(0, "err_missing_columns", {"columns": ", ".join(missing)})]
    for col in OPTIONAL:
        if col not in df.columns:
            df[col] = None

    df = df.dropna(how="all")  # пустые строки в конце таблицы — не ошибка
    if df.empty:
        return [], [ImportError_(0, "err_no_rows")]
    if len(df) > MAX_ROWS:
        return [], [ImportError_(0, "err_too_many_rows", {"n": len(df), "max": MAX_ROWS})]

    region_ids = region_lookup(regions)
    rows: list[ImportRow] = []
    errors: list[ImportError_] = []
    seen_offer: dict[tuple, int] = {}  # (модель, артикул, регион, дилер) → строка
    seen_part: dict[tuple, tuple[int, str]] = {}  # (модель, артикул) → (строка, категория)

    for index, raw in df.iterrows():
        if len(errors) >= MAX_ERRORS:
            break
        excel_row = int(index) + 2  # +1 за заголовок, +1 потому что Excel считает с 1
        v = {col: _clean(raw.get(col)) for col in REQUIRED + OPTIONAL}
        row_errors = []

        for col in REQUIRED:
            if v[col] is None:
                row_errors.append(ImportError_(excel_row, "err_empty", {"column": col}))
        for col, limit in COLUMN_LIMITS.items():
            if v[col] and len(v[col]) > limit:
                row_errors.append(ImportError_(excel_row, "err_too_long", {"column": col, "max": limit}))

        region_id = find_region(v["region"], region_ids)
        if v["region"] and region_id is None:
            row_errors.append(ImportError_(excel_row, "err_region", {"value": v["region"]}))

        price = _to_decimal(v["price"])
        if v["price"] and (price is None or price == 0):
            row_errors.append(ImportError_(excel_row, "err_price", {"value": v["price"]}))
        stock = _to_int(v["stock"])
        if v["stock"] and stock is None:
            row_errors.append(ImportError_(excel_row, "err_stock", {"value": v["stock"]}))
        delivery = _to_int(v["delivery_days"])
        if v["delivery_days"] and delivery is None:
            row_errors.append(ImportError_(excel_row, "err_delivery", {"value": v["delivery_days"]}))

        if not row_errors:
            model_key = v["model_ru"].lower()
            offer = (model_key, v["part_number"].lower(), dealer_key(v["dealer"]))
            if offer in seen_offer:
                row_errors.append(ImportError_(excel_row, "err_duplicate", {"other": seen_offer[offer]}))
            part_key = (model_key, v["part_number"].lower())
            if part_key in seen_part and seen_part[part_key][1] != v["node_ru"].lower():
                row_errors.append(ImportError_(excel_row, "err_conflict_node", {
                    "number": v["part_number"], "model": v["model_ru"], "other": seen_part[part_key][0],
                }))
            seen_offer.setdefault(offer, excel_row)
            seen_part.setdefault(part_key, (excel_row, v["node_ru"].lower()))

        if row_errors:
            errors.extend(row_errors)
            continue
        rows.append(ImportRow(
            row=excel_row,
            region_id=region_id,
            dealer=v["dealer"],
            model={"ru": v["model_ru"], "en": v["model_en"], "uz": v["model_uz"]},
            node={"ru": v["node_ru"], "en": v["node_en"], "uz": v["node_uz"]},
            part_name={"ru": v["part_name_ru"], "en": v["part_name_en"], "uz": v["part_name_uz"]},
            part_number=v["part_number"],
            price=price,
            stock=stock,
            delivery_days=delivery,
            description={"ru": v["description_ru"], "en": v["description_en"], "uz": v["description_uz"]},
            photo=v["photo"],
        ))
    return rows, errors


# ---------- складская выгрузка («Список запчастей») ----------

WAREHOUSE_REQUIRED = ["Кол-во", "Код запчасти", "Название запчасти", "Статус", "Тип запчасти",
                      "Автомобильная марка", mapping.PRICE_COLUMN, mapping.FALLBACK_PRICE_COLUMN, "На Дилера"]
EMPTY_MARKS = {None, "—", "-", "–"}


def _find_warehouse_header(path: Path) -> tuple[str, int] | None:
    """Ищем строку заголовков складской выгрузки в первых 20 строках любого листа."""
    try:
        book = pd.read_excel(path, sheet_name=None, header=None, nrows=20, dtype=str, engine="openpyxl")
    except Exception:
        return None
    for sheet, df in book.items():
        for i, row in df.iterrows():
            values = {_clean(v) for v in row.tolist()}
            if {"Код запчасти", "На Дилера"} <= values:
                return sheet, int(i)
    return None


def _model_names(raw: str | None) -> list[tuple[str, str, str]]:
    """'T9-P33Z3,T8-P30BF' → две модели; 'RF8-V9AA3,V9HA0' → RF8-V9AA3 и RF8-V9HA0; '—' → «Все модели»."""
    if raw in EMPTY_MARKS:
        return [mapping.ALL_MODELS]
    codes, prefix = [], ""
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if "-" in token:
            prefix = token.split("-", 1)[0] + "-"
        elif prefix and token not in mapping.MODEL_NAMES:
            token = prefix + token  # продолжение списка без префикса
        codes.append(token)
    names = dict.fromkeys(mapping.MODEL_NAMES.get(code, code) for code in codes)  # без повторов
    return [(name, name, name) for name in names] or [mapping.ALL_MODELS]


def validate_warehouse(path: Path, regions: list[Region], sheet: str, header_row: int,
                       known_dealers: dict[str, int] | None = None):
    """Складская выгрузка → строки каталога. Неподходящие строки пропускаются с предупреждением.
    known_dealers: ключ дилера → регион из справочника дилеров (он главнее import_mapping.py)."""
    known_dealers = known_dealers or {}
    mapped_regions = {dealer_key(name): code for name, code in mapping.DEALER_REGIONS.items()}
    errors: list[ImportError_] = []
    warnings: list[ImportError_] = []
    df = pd.read_excel(path, sheet_name=sheet, header=header_row, dtype=str, engine="openpyxl")
    df.columns = [_clean(c) or "" for c in df.columns]
    missing = [c for c in WAREHOUSE_REQUIRED if c not in df.columns]
    if missing:
        return [], [ImportError_(0, "err_missing_columns", {"columns": ", ".join(missing)})], []

    region_by_code = {r.code: r.id for r in regions}
    for code in {*mapping.DEALER_REGIONS.values(), mapping.DEFAULT_REGION}:
        if code not in region_by_code:
            errors.append(ImportError_(0, "err_mapping_region", {"code": code}))
    if errors:
        return [], errors, []

    skipped_status: dict[str, int] = {}
    no_price, no_dealer = 0, 0
    default_region_dealers: set[str] = set()
    unknown_models: set[str] = set()
    untranslated: set[str] = set()
    offers: dict[tuple, dict] = {}  # (модель, артикул, дилер) → собранная строка

    data = df[df["Код запчасти"].map(_clean).notna()]  # итоговые строки внизу таблицы без артикула
    for index, raw in data.iterrows():
        excel_row = int(index) + header_row + 2
        v = {c: _clean(raw.get(c)) for c in df.columns}
        status = v.get("Статус") or "—"
        if status not in mapping.AVAILABLE_STATUSES:
            skipped_status[status] = skipped_status.get(status, 0) + 1
            continue
        dealer = v.get("На Дилера")
        if dealer in EMPTY_MARKS:
            no_dealer += 1
            continue
        qty = _to_int(v.get("Кол-во"))
        if not v.get("Название запчасти") or qty is None:
            warnings.append(ImportError_(excel_row, "warn_bad_row"))
            continue
        price = _to_decimal(v.get(mapping.PRICE_COLUMN))
        if not price:
            price = _to_decimal(v.get(mapping.FALLBACK_PRICE_COLUMN))
        if not price:
            no_price += 1
            continue
        key_d = dealer_key(dealer)
        if key_d in known_dealers:
            region_id = known_dealers[key_d]
        elif key_d in mapped_regions:
            region_id = region_by_code[mapped_regions[key_d]]
        else:
            default_region_dealers.add(dealer)
            region_id = region_by_code[mapping.DEFAULT_REGION]
        node = mapping.CATEGORIES.get((v.get("Тип запчасти") or "").upper(), mapping.OTHER_CATEGORY)
        updated = pd.to_datetime(v.get("Дата обновления"), format="%d.%m.%Y %H:%M:%S", errors="coerce")

        if not has_translation(v["Название запчасти"]):
            untranslated.add(v["Название запчасти"])
        known_names = set(mapping.MODEL_NAMES.values()) | {mapping.ALL_MODELS[0]}
        for model in _model_names(v.get("Автомобильная марка")):
            if model[0] not in known_names:
                unknown_models.add(model[0])
            key = (model[0].lower(), v["Код запчасти"].lower(), key_d)
            offer = offers.get(key)
            if offer is None:
                offers[key] = {"row": excel_row, "region_id": region_id, "dealer": dealer, "model": model,
                               "node": node, "name": v["Название запчасти"], "number": v["Код запчасти"],
                               "qty": qty, "price": price, "updated": updated}
            else:  # одна деталь у одного дилера в нескольких строках (разные инвойсы) — суммируем
                offer["qty"] += qty
                if pd.notna(updated) and (pd.isna(offer["updated"]) or updated > offer["updated"]):
                    offer["price"], offer["updated"] = price, updated  # цена — из самой свежей строки

    for status, n in sorted(skipped_status.items()):
        warnings.append(ImportError_(0, "warn_skipped_status", {"status": status, "n": n}))
    if no_dealer:
        warnings.append(ImportError_(0, "warn_no_dealer", {"n": no_dealer}))
    if no_price:
        warnings.append(ImportError_(0, "warn_no_price", {"n": no_price}))
    if default_region_dealers:
        warnings.append(ImportError_(0, "warn_default_region", {
            "n": len(default_region_dealers), "dealers": ", ".join(sorted(default_region_dealers)),
        }))
    if untranslated:
        sample = sorted(untranslated)[:10]
        warnings.append(ImportError_(0, "warn_untranslated", {
            "n": len(untranslated), "names": ", ".join(sample) + ("…" if len(untranslated) > 10 else ""),
        }))
    if unknown_models:
        warnings.append(ImportError_(0, "warn_unknown_models", {"models": ", ".join(sorted(unknown_models))}))
    if not offers:
        errors.append(ImportError_(0, "err_no_rows"))

    rows = [
        ImportRow(
            row=o["row"], region_id=o["region_id"], dealer=o["dealer"],
            model=dict(zip(("ru", "en", "uz"), o["model"])), node=dict(zip(("ru", "en", "uz"), o["node"])),
            part_name=translate(o["name"]),
            part_number=o["number"], price=o["price"], stock=o["qty"], delivery_days=None,
            description={"ru": None, "en": None, "uz": None}, photo=None,
        )
        for o in offers.values()
    ]
    return rows, errors, warnings


def validate_any(path: Path, regions: list[Region], known_dealers: dict[str, int] | None = None):
    """Определяем формат файла сами: справочник дилеров, складская выгрузка или наш шаблон.
    Возвращает (строки, ошибки, предупреждения, формат)."""
    if is_directory(path):
        rows, errors = validate_directory(path, regions)
        return rows, errors, [], "directory"
    found = _find_warehouse_header(path)
    if found:
        rows, errors, warnings = validate_warehouse(path, regions, *found, known_dealers=known_dealers)
        return rows, errors, warnings, "warehouse"
    rows, errors = validate_file(path, regions)
    return rows, errors, [], "template"


# ---------- запись в базу ----------

def _set_names(obj, names: dict, prefix: str = "name") -> None:
    setattr(obj, f"{prefix}_ru", names["ru"])
    for lang in ("en", "uz"):
        if names.get(lang):  # пустой перевод в файле не стирает существующий
            setattr(obj, f"{prefix}_{lang}", names[lang])


async def apply_import(session: AsyncSession, rows: list[ImportRow]) -> ImportStats:
    """Записать строки в базу. Коммит/rollback делает вызывающий код."""
    stats = ImportStats()

    # Всё существующее загружаем одним запросом на таблицу — быстро даже для 50 000 строк
    models = {m.name_ru.lower(): m for m in (await session.scalars(select(CarModel))).unique()}
    nodes = {n.name_ru.lower(): n for n in (await session.scalars(select(Node))).unique()}
    dealers = {d.name_key: d for d in (await session.scalars(select(Dealer))).unique()}

    # 1. Модели, категории, дилеры
    for r in rows:
        model = models.get(r.model["ru"].lower())
        if model is None:
            model = models[r.model["ru"].lower()] = CarModel(name_ru=r.model["ru"])
            session.add(model)
        _set_names(model, r.model)
        model.active = True

        node = nodes.get(r.node["ru"].lower())
        if node is None:
            node = nodes[r.node["ru"].lower()] = Node(name_ru=r.node["ru"])
            session.add(node)
        _set_names(node, r.node)
        node.active = True

        key = dealer_key(r.dealer)
        if key not in dealers:
            dealers[key] = Dealer(region_id=r.region_id, name=r.dealer, name_key=key)
            session.add(dealers[key])
        elif not dealers[key].in_directory:
            dealers[key].region_id = r.region_id  # регион из справочника дилеров не перезаписываем
        dealers[key].active = True
    await session.flush()  # получаем id новых записей

    # 2. Детали
    parts = {(p.model_id, p.part_number.lower()): p for p in (await session.scalars(select(Part))).unique()}
    counted: set[tuple] = set()
    for r in rows:
        model = models[r.model["ru"].lower()]
        key = (model.id, r.part_number.lower())
        part = parts.get(key)
        if key not in counted:
            counted.add(key)
            if part is None:
                stats.new += 1
            else:
                stats.updated += 1
        if part is None:
            part = parts[key] = Part(model_id=model.id, part_number=r.part_number)
            session.add(part)
        part.node_id = nodes[r.node["ru"].lower()].id
        _set_names(part, r.part_name)
        if r.description["ru"]:
            _set_names(part, r.description, prefix="description")
        if r.photo:
            part.photo = r.photo
        part.active = True
    await session.flush()
    seen_parts = {parts[k].id for k in counted}

    # 3. Цены и остатки
    stocks = {(s.part_id, s.dealer_id): s for s in await session.scalars(select(Stock))}
    seen_stocks: set[tuple] = set()
    for r in rows:
        part = parts[(models[r.model["ru"].lower()].id, r.part_number.lower())]
        dealer = dealers[dealer_key(r.dealer)]
        key = (part.id, dealer.id)
        stock = stocks.get(key)
        if stock is None:
            stock = stocks[key] = Stock(part_id=part.id, dealer_id=dealer.id)
            session.add(stock)
        stock.price = r.price
        stock.quantity = r.stock
        stock.delivery_days = r.delivery_days
        seen_stocks.add(key)

    # 3б. Детали в незакрытых заказах бота уже обещаны покупателям. Складская программа о них
    # не знает, поэтому вычитаем их из нового остатка — иначе одну деталь можно продать дважды.
    reserved_rows = await session.execute(
        select(OrderItem.part_id, Order.dealer_id, func.sum(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status.in_(("NEW", "CONFIRMED", "READY")), OrderItem.part_id.is_not(None))
        .group_by(OrderItem.part_id, Order.dealer_id)
    )
    for part_id, dealer_id, qty in reserved_rows.all():
        stock = stocks.get((part_id, dealer_id))
        if stock is not None and (part_id, dealer_id) in seen_stocks:
            taken = min(stock.quantity, int(qty))
            stock.quantity -= taken
            stats.reserved += taken

    # 4. Всё, чего нет в файле, скрываем (файл = полный прайс)
    for part in parts.values():
        if part.id not in seen_parts and part.active:
            part.active = False
            stats.hidden += 1
    for key, stock in stocks.items():
        if key not in seen_stocks:
            await session.delete(stock)
    seen_dealers = {dealer_key(r.dealer) for r in rows}
    for key, dealer in dealers.items():
        if key not in seen_dealers:
            dealer.active = False
    await session.flush()

    stats.models = len({r.model["ru"].lower() for r in rows})
    stats.nodes = len({r.node["ru"].lower() for r in rows})
    stats.parts = len(counted)
    stats.dealers = len(seen_dealers)
    stats.regions = len({dealers[k].region_id for k in seen_dealers})
    return stats
