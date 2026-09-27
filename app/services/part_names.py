"""Переводы названий деталей (в складской выгрузке они только на английском).

Словарь: app/data/part_names.json — «английское название» → {"ru": ..., "uz": ...}.
Новое название без перевода покажется по-английски, а бот при загрузке предупредит.
Чтобы добавить перевод — допишите строку в JSON по образцу и загрузите выгрузку заново.
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


def translate(english: str) -> dict[str, str | None]:
    """→ {"ru": ..., "en": ..., "uz": ...}. Без перевода ru = английское название (uz покажет его же)."""
    tr = _dictionary().get(part_name_key(english), {})
    return {"ru": tr.get("ru") or english, "en": english, "uz": tr.get("uz")}


def has_translation(english: str) -> bool:
    return part_name_key(english) in _dictionary()
