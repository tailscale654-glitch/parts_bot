from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Region
from app.services.localization import i18n, localized_name


def region_keyboard(regions: list[Region], lang: str, with_back: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=localized_name(r, lang), callback_data=f"region:{r.id}")]
        for r in regions
    ]
    if with_back:  # при смене региона можно вернуться в меню, не выбирая
        rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_back"), callback_data="profile:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
