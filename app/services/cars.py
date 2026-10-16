"""Автомобиль клиента: модели, комплектации и цвета для выбора при регистрации.

Источники: сайт jacmotors.uz/models (октябрь 2026) и коммерческое предложение JAC MOTORS TOSHKENT (2025).
Цвета — объединение обоих источников (у клиента может быть машина прошлого года выпуска).
Этот файл можно править без знания Python — меняйте только текст в кавычках.

catalog — модель в каталоге бота (как её называет CarSale через import_mapping.py), её запчасти и показываем.
Шаг «Комплектация» показывается, только если у модели их больше одной.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.database.models import User
from app.services.localization import i18n

# ключ → (русский, английский, узбекский)
COLORS = {
    "white": ("Белый", "White", "Oq"),
    "black": ("Чёрный", "Black", "Qora"),
    "silver": ("Серебристый", "Silver", "Kumushrang"),
    "gray": ("Серый", "Gray", "Kulrang"),
    "metallic_gray": ("Серый металлик", "Metallic gray", "Metallik kulrang"),
    "star_gray": ("Звёздный серый", "Star gray", "Och kulrang"),
    "red": ("Красный", "Red", "Qizil"),
    "blue": ("Синий", "Blue", "Ko‘k"),
}

# комплектации: на сайте это отдельные модели (JAC M3 и JAC M3 VAN, JAC Sunray и JAC Sunray VAN)
MODIFICATIONS = {
    "passenger": ("Пассажирский (9 мест)", "Passenger (9 seats)", "Yo‘lovchi (9 o‘rinli)"),
    "minibus": ("Микроавтобус (16 мест)", "Minibus (16 seats)", "Mikroavtobus (16 o‘rinli)"),
    "van": ("VAN (фургон)", "VAN (cargo)", "VAN (furgon)"),
}


@dataclass(frozen=True)
class Car:
    name: str  # как видит клиент
    catalog: str  # модель в каталоге бота
    colors: tuple[str, ...]
    mods: tuple[str, ...] = ()
    mod_colors: dict = field(default_factory=dict)  # комплектация → свои цвета (если отличаются)


CARS = [
    Car("JAC M3", "JAC M3", ("white", "black", "silver"), ("passenger", "van")),
    Car("JAC M4", "JAC M4 Luxe", ("white", "black", "silver")),
    Car("JAC Sunray", "JAC Sunray", ("white", "black", "silver", "gray", "metallic_gray"), ("minibus", "van")),
    Car("JAC T8", "JAC T8", ("white", "black", "silver", "gray")),
    Car("JAC T9", "JAC T9", ("white", "black", "silver", "metallic_gray", "star_gray")),
    Car("JAC JS8", "JAC JS8", ("white", "black", "red", "metallic_gray")),
    Car("JAC RF8", "JAC RF8", ("white", "gray", "blue")),
]
LANG_INDEX = {"ru": 0, "en": 1, "uz": 2}


def _t(names: tuple[str, str, str] | None, lang: str | None) -> str | None:
    return names[LANG_INDEX.get(lang or "ru", 0)] if names else None


def models() -> list[str]:
    return [c.name for c in CARS]


def get(name: str | None) -> Car | None:
    return next((c for c in CARS if c.name == name), None)


def modifications(model: str | None) -> list[str]:
    car = get(model)
    return list(car.mods) if car else []


def colors(model: str | None, mod: str | None = None) -> list[str]:
    car = get(model)
    if car is None:
        return list(COLORS)
    return list(car.mod_colors.get(mod, car.colors))


def color_name(key: str | None, lang: str | None) -> str | None:
    return _t(COLORS.get(key or ""), lang)


def mod_name(key: str | None, lang: str | None) -> str | None:
    return _t(MODIFICATIONS.get(key or ""), lang)


def catalog_model(user: User) -> str | None:
    """Модель каталога для автомобиля клиента (старые записи — название модели каталога как есть)."""
    car = get(user.car_model)
    return car.catalog if car else user.car_model


def carsale_code(user: User) -> str | None:
    """Код модификации CarSale для фильтра деталей. Комплектации из предложения с кодами CarSale
    не связаны — фильтр по модификации пока не используется (детали модели видны все)."""
    return None


def car_text(user: User, lang: str | None) -> str | None:
    """«JAC M3 · VAN (фургон) · Белый» — или None, если автомобиль не выбран."""
    if not user.car_model:
        return None
    return " · ".join(filter(None, [user.car_model, mod_name(user.car_modification, lang),
                                    color_name(user.car_color, lang)]))


def needs_car(user: User) -> bool:
    return not user.car_model


def car_line(user: User, lang: str | None) -> str:
    return i18n.t(lang, "car_line", car=car_text(user, lang) or i18n.t(lang, "car_not_selected"))
