"""Логика каталога, не зависящая от Telegram: пагинация и текст карточки детали."""
import math
from dataclasses import dataclass

from app.database.models import Part
from app.services.localization import i18n, localized_name

PAGE_SIZE = 8


@dataclass
class Page:
    number: int  # с 1
    total_pages: int
    offset: int

    @property
    def has_prev(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.total_pages


def paginate(total_items: int, requested_page: int, page_size: int = PAGE_SIZE) -> Page:
    """Номер страницы всегда в допустимых пределах (защита от подделанных callback)."""
    total_pages = max(1, math.ceil(total_items / page_size))
    number = min(max(1, requested_page), total_pages)
    return Page(number=number, total_pages=total_pages, offset=(number - 1) * page_size)


def part_card_text(part: Part, lang: str | None) -> str:
    lines = [
        f"📦 {localized_name(part, lang).upper()}",
        "",
        i18n.t(lang, "part_model", model=localized_name(part.model, lang)),
        i18n.t(lang, "part_node", node=localized_name(part.node, lang)),
        "",
        i18n.t(lang, "part_number", number=part.part_number),
    ]
    description = getattr(part, f"description_{lang}", None) or part.description_ru
    if description:
        lines += ["", description]
    lines += ["", i18n.t(lang, "prices_coming_soon")]
    return "\n".join(lines)
