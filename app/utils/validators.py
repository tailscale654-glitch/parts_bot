"""Проверка данных, пришедших от пользователя."""
import re


def normalize_phone(raw: str | None) -> str | None:
    """'998 90 123-45-67' / '+998901234567' → '+998901234567'. Неверный номер → None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:  # международный стандарт E.164: до 15 цифр
        return None
    return f"+{digits}"
