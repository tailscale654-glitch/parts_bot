"""Сравнение названий дилеров, записанных по-разному."""
import re

LEGAL_FORMS = r"\b(ооо|ooo|oоо|llc|mchj|мчж|ип|сп|xk|ok|ltd)\b"


def dealer_key(name: str | None) -> str:
    """«OOO «ASIAMOTOR»» и «"Asia Motor" MChJ» → «asiamotor» (без ООО/MChJ, кавычек, пробелов, дефисов)."""
    text = str(name or "").lower().replace(" ", " ")
    text = re.sub(r"[«»\"'`‘’“”]", " ", text)
    text = re.sub(LEGAL_FORMS, " ", text)
    return re.sub(r"[^0-9a-zа-яёўқғҳ]", "", text)
