"""Выбор автомобиля клиента: модель → комплектация (если их несколько) → цвет."""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import cars


class CarCB(CallbackData, prefix="car"):
    action: str  # start | model | mod | color
    i: int = 0  # номер модели / комплектации / цвета в списке


def _grid(buttons, columns: int = 2):
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]


def models_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=name, callback_data=CarCB(action="model", i=i).pack())
               for i, name in enumerate(cars.models())]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons))


def mods_keyboard(model: str, lang: str | None) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=cars.mod_name(key, lang), callback_data=CarCB(action="mod", i=i).pack())
               for i, key in enumerate(cars.modifications(model))]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons, 1))


def colors_keyboard(model: str, mod: str | None, lang: str | None) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=cars.color_name(key, lang), callback_data=CarCB(action="color", i=i).pack())
               for i, key in enumerate(cars.colors(model, mod))]
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons))
