"""Автомобиль клиента: модели, модификации (коды CarSale) и цвета для выбора при регистрации.

Модели и модификации берутся из import_mapping.py (MODEL_NAMES): код CarSale → модель в боте.
Модификация — полный код CarSale с дефисом («RF8-V9AA3»). Шаг «Модификация» показывается,
только если у модели их больше одной.
"""
from __future__ import annotations

from app.database.models import User
from app.services import import_mapping as mapping
from app.services.localization import i18n

# ключ → (русский, английский, узбекский)
COLORS = {
    "white": ("Белый", "White", "Oq"),
    "black": ("Чёрный", "Black", "Qora"),
    "gray": ("Серый", "Gray", "Kulrang"),
    "silver": ("Серебристый", "Silver", "Kumushrang"),
    "red": ("Красный", "Red", "Qizil"),
    "blue": ("Синий", "Blue", "Ko‘k"),
    "other": ("Другой", "Other", "Boshqa"),
}
LANG_INDEX = {"ru": 0, "en": 1, "uz": 2}


def models() -> list[str]:
    """Модели автомобилей для выбора (без «Прочее»), по алфавиту."""
    return sorted(set(mapping.MODEL_NAMES.values()) - {mapping.ALL_MODELS[0]})


def modifications(model: str | None) -> list[str]:
    """Коды модификаций CarSale этой модели: JAC RF8 → [RF8-V9AA3, RF8-V9HA0]."""
    return sorted(code for code, name in mapping.MODEL_NAMES.items() if name == model and "-" in code)


def color_name(key: str | None, lang: str | None) -> str | None:
    names = COLORS.get(key or "")
    return names[LANG_INDEX.get(lang or "ru", 0)] if names else None


def car_text(user: User, lang: str | None) -> str | None:
    """«JAC RF8 · RF8-V9AA3 · Белый» — или None, если автомобиль не выбран."""
    if not user.car_model:
        return None
    return " · ".join(filter(None, [user.car_model, user.car_modification, color_name(user.car_color, lang)]))


def needs_car(user: User) -> bool:
    return not user.car_model


def car_line(user: User, lang: str | None) -> str:
    return i18n.t(lang, "car_line", car=car_text(user, lang) or i18n.t(lang, "car_not_selected"))
