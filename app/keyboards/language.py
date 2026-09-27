from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

LANGUAGE_BUTTONS = [
    ("ru", "🇷🇺 Русский"),
    ("en", "🇬🇧 English"),
    ("uz", "🇺🇿 O‘zbekcha"),
]


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"lang:{code}")]
            for code, title in LANGUAGE_BUTTONS
        ]
    )
