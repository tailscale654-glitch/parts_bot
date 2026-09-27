"""Сравнение названий, записанных по-разному."""
import re

LEGAL_FORMS = r"\b(ооо|ooo|oоо|llc|mchj|мчж|ип|сп|xk|ok|ltd)\b"


def dealer_key(name: str | None) -> str:
    """«OOO «ASIAMOTOR»» и «"Asia Motor" MChJ» → «asiamotor» (без ООО/MChJ, кавычек, пробелов, дефисов)."""
    text = str(name or "").lower().replace(" ", " ")
    text = re.sub(r"[«»\"'`‘’“”]", " ", text)
    text = re.sub(LEGAL_FORMS, " ", text)
    return re.sub(r"[^0-9a-zа-яёўқғҳ]", "", text)


def part_name_key(name: str | None) -> str:
    """«LEFT OUTER REARVIEW MIRROR ASSY.（SILVER）» → «left outer rearview mirror assy.(silver)».
    Регистр, лишние пробелы, китайские скобки и запятые не важны."""
    text = str(name or "").lower().replace(" ", " ")
    text = text.replace("（", "(").replace("）", ")").replace("、", ",")
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ") ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(".").strip()
