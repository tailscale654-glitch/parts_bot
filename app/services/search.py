"""Поиск детали по названию и артикулу: нормализация текста и порядок результатов."""
import re

APOSTROPHES = re.compile(r"[‘’'`ʻʼ]")
NOT_ALNUM = re.compile(r"[^0-9a-zа-я]")


def norm(text: str | None) -> str:
    """Регистр, «ё», апострофы узбекского (o‘ / o' / oʻ) и лишние пробелы не мешают поиску."""
    text = APOSTROPHES.sub("", (text or "").casefold().replace("ё", "е"))
    return " ".join(text.split())


def compact(text: str | None) -> str:
    """Артикул без пробелов, дефисов и точек: «1017100-GD050» = «1017100GD050»."""
    return NOT_ALNUM.sub("", norm(text))


def _names(row) -> str:
    return norm(" ".join(filter(None, (row.name_ru, row.name_en, row.name_uz))))


def matches(query: str, row) -> bool:
    """Все слова запроса есть в названии (на любом языке) — или запрос похож на часть артикула."""
    words = norm(query).split()
    if not words:
        return False
    code = compact(query)
    if len(code) >= 3 and code in compact(row.part_number):
        return True
    names = _names(row)
    return all(w in names for w in words)


def rank(query: str, row, lang: str | None) -> tuple:
    """Сначала точный артикул, потом артикул с начала, потом название с начала, потом остальное (по алфавиту)."""
    code, number = compact(query), compact(row.part_number)
    name = norm(getattr(row, f"name_{lang}", None) or row.name_ru)
    if code and number == code:
        score = 0
    elif code and number.startswith(code):
        score = 1
    elif name.startswith(norm(query)):
        score = 2
    else:
        score = 3
    return score, name
