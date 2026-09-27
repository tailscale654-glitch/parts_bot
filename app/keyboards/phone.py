from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.services.localization import i18n


def phone_keyboard(lang: str, with_cancel: bool = False) -> ReplyKeyboardMarkup:
    """Кнопка Telegram «Отправить контакт» — номер вручную вводить не нужно."""
    rows = [[KeyboardButton(text=i18n.t(lang, "btn_share_phone"), request_contact=True)]]
    if with_cancel:  # при смене номера можно передумать
        rows.append([KeyboardButton(text=i18n.t(lang, "btn_cancel"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)
