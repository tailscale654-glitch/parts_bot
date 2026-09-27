from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.localization import i18n

# callback_data одинаковый для всех языков — меняется только подпись кнопки
MAIN_MENU_ITEMS = [
    ("btn_catalog", "menu:catalog"),
    ("btn_my_orders", "menu:orders"),
    ("btn_change_region", "menu:region"),
    ("btn_change_language", "menu:language"),
    ("btn_contact_manager", "menu:contact"),
]


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n.t(lang, key), callback_data=data)]
            for key, data in MAIN_MENU_ITEMS
        ]
    )


def back_to_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=i18n.t(lang, "btn_main_menu"), callback_data="menu:home")]]
    )
