"""Выбор автомобиля клиента: модель → цвет → модификация (если их несколько)."""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import cars
from app.services.localization import i18n


class CarCB(CallbackData, prefix="car"):
    action: str  # start | model | color | mod
    i: int = 0  # номер модели / модификации в списке (-1 — «не знаю»)
    key: str = ""  # ключ цвета


def _grid(buttons, columns: int = 2):
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]


def models_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=name, callback_data=CarCB(action="model", i=i).pack())
               for i, name in enumerate(cars.models())]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons))


def colors_keyboard(lang: str | None) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=cars.color_name(key, lang), callback_data=CarCB(action="color", key=key).pack())
               for key in cars.COLORS]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons))


def mods_keyboard(model: str, lang: str | None) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=code, callback_data=CarCB(action="mod", i=i).pack())
               for i, code in enumerate(cars.modifications(model))]
    rows = _grid(buttons) + [[InlineKeyboardButton(text=i18n.t(lang, "btn_mod_unknown"),
                                                   callback_data=CarCB(action="mod", i=-1).pack())]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
