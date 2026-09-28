"""Переводы названий деталей (в складской выгрузке они только на английском).

Словарь: app/data/part_names.json — «английское название» → {"ru": ..., "uz": ...}.
Поверх словаря — переводы из веб-панели (таблица part_translations, «Каталог → перевести»):
они главнее JSON и не теряются при новой загрузке. Их передают сюда как overrides:
{ключ названия: {"ru": ..., "uz": ...}}.
Новое название без перевода покажется по-английски, а бот при загрузке предупредит.
"""
import json
from functools import lru_cache
from pathlib import Path

from app.utils.names import part_name_key

DICTIONARY = Path(__file__).resolve().parent.parent / "data" / "part_names.json"


@lru_cache(maxsize=1)
def _dictionary() -> dict[str, dict[str, str]]:
    if not DICTIONARY.exists():
        return {}
    with DICTIONARY.open(encoding="utf-8") as f:
        return {part_name_key(k): v for k, v in json.load(f).items()}


Overrides = dict[str, dict[str, str | None]]


def _lookup(english: str, overrides: Overrides | None) -> dict[str, str | None]:
    key = part_name_key(english)
    base = _dictionary().get(key, {})
    extra = (overrides or {}).get(key, {})
    return {lang: extra.get(lang) or base.get(lang) for lang in ("ru", "uz")}


def translate(english: str, overrides: Overrides | None = None) -> dict[str, str | None]:
    """→ {"ru": ..., "en": ..., "uz": ...}. Без перевода ru = английское название (uz покажет его же)."""
    tr = _lookup(english, overrides)
    return {"ru": tr["ru"] or english, "en": english, "uz": tr["uz"]}


def has_translation(english: str, overrides: Overrides | None = None) -> bool:
    tr = _lookup(english, overrides)
    return bool(tr["ru"] or tr["uz"])
