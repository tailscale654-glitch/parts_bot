"""Настройки бота из веб-панели («⚙️ Настройки»): контакты для кнопки «📞 Менеджер»."""
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotSetting
from app.services.localization import i18n

# ключ → подпись в панели
CONTACT_FIELDS = {
    "contact_phone": "Телефон",
    "contact_phone2": "Второй телефон",
    "contact_telegram": "Telegram менеджера (@username)",
    "contact_hours": "Часы работы",
    "contact_address": "Адрес",
}


async def load(session: AsyncSession) -> dict[str, str]:
    rows = await session.scalars(select(BotSetting))
    return {s.key: s.value for s in rows}


async def save(session: AsyncSession, values: dict[str, str]) -> None:
    current = {s.key: s for s in await session.scalars(select(BotSetting).where(BotSetting.key.in_(values)))}
    for key, value in values.items():
        if key in current:
            current[key].value = value
        else:
            session.add(BotSetting(key=key, value=value))
    await session.commit()


def telegram_username(value: str | None) -> str:
    """«@jac_manager», «t.me/jac_manager», «https://t.me/jac_manager» → «jac_manager»."""
    value = (value or "").strip()
    value = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)", "", value).lstrip("@")
    return value if re.fullmatch(r"[A-Za-z0-9_]{4,32}", value) else ""


def contact_view(values: dict[str, str], lang: str | None) -> tuple[str, InlineKeyboardMarkup | None]:
    """Текст и кнопка для «📞 Менеджер». Если в панели ничего не заполнено — прежний общий текст."""
    lines = []
    for key, label_key in (("contact_phone", "contact_phone_label"), ("contact_phone2", "contact_phone_label"),
                           ("contact_hours", "contact_hours_label"), ("contact_address", "contact_address_label")):
        if values.get(key, "").strip():
            lines.append(f"{i18n.t(lang, label_key)}: {values[key].strip()}")
    username = telegram_username(values.get("contact_telegram"))
    if username:
        lines.append(f"Telegram: @{username}")
    if not lines:
        return i18n.t(lang, "contact_manager_text"), None
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=i18n.t(lang, "contact_write_btn"), url=f"https://t.me/{username}")]]) if username else None
    return i18n.t(lang, "contact_card_title") + "\n\n" + "\n".join(lines), kb
