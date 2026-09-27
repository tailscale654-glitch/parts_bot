"""Постоянное меню внизу экрана (как в EVOS)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.services.localization import i18n

MENU_LAYOUT = [
    ["btn_catalog", "btn_cart"],
    ["btn_my_orders", "btn_profile"],
    ["btn_manager"],
]
MENU_KEYS = [key for row in MENU_LAYOUT for key in row] + ["btn_cancel"]


def main_reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=i18n.t(lang, key)) for key in row] for row in MENU_LAYOUT],
        resize_keyboard=True,
        is_persistent=True,  # меню всегда видно, не прячется
    )


def menu_action(text: str | None) -> str | None:
    """Текст нажатой кнопки меню (на любом из 3 языков) → её ключ, например 'btn_cart'."""
    if not text:
        return None
    for key in MENU_KEYS:
        for lang in i18n.languages:
            if i18n.t(lang, key) == text:
                return key
    return None


def profile_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        ("btn_change_phone", "profile:phone"),
        ("btn_change_region", "menu:region"),
        ("btn_change_language", "menu:language"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=i18n.t(lang, k), callback_data=d)] for k, d in rows]
    )
