"""Логика каталога, не зависящая от Telegram: пагинация и текст карточки детали."""
import math
from dataclasses import dataclass

from decimal import Decimal

from app.database.models import CartItem, Part, Region, Stock
from app.database.repositories.cart import is_available
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


MAX_OFFERS_SHOWN = 6


def money(value: Decimal | int, lang: str | None) -> str:
    """85000 → «85 000 сум»."""
    value = Decimal(value)
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{text.replace(',', ' ')} {i18n.t(lang, 'currency')}"


def offer_lines(stock: Stock, lang: str | None) -> list[str]:
    lines = [f"🏢 {stock.dealer.name}"]
    if stock.dealer.address:
        lines.append(f"📌 {stock.dealer.address}")
    if stock.dealer.phone:
        lines.append(f"📞 {stock.dealer.phone}")
    lines.append(f"💰 {money(stock.price, lang)}")
    if stock.quantity > 0:
        lines.append(i18n.t(lang, "in_stock", n=stock.quantity))
    elif stock.delivery_days:
        lines.append(i18n.t(lang, "on_order", days=stock.delivery_days))
    else:
        lines.append(i18n.t(lang, "out_of_stock"))
    return lines


def part_card_text(
    part: Part, lang: str | None, region: Region | None = None,
    offers: list[Stock] | None = None, regions_elsewhere: int = 0,
) -> str:
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
    if region is not None:
        lines += ["", f"📍 {localized_name(region, lang).upper()}"]
    if offers:
        for stock in offers[:MAX_OFFERS_SHOWN]:
            lines += [""] + offer_lines(stock, lang)
        if len(offers) > MAX_OFFERS_SHOWN:
            lines += ["", i18n.t(lang, "more_dealers", n=len(offers) - MAX_OFFERS_SHOWN)]
    else:
        lines += ["", i18n.t(lang, "no_offers_in_region")]
        if regions_elsewhere:
            lines.append(i18n.t(lang, "offers_elsewhere", n=regions_elsewhere))
    return "\n".join(lines)


def cart_text(items: list[CartItem], lang: str | None) -> str:
    lines = [i18n.t(lang, "cart_title"), ""]
    total = Decimal(0)
    for n, item in enumerate(items, start=1):
        stock = item.stock
        part = stock.part
        lines.append(f"{n}. {localized_name(part, lang)} ({part.part_number})")
        lines.append(f"    🏢 {stock.dealer.name}")
        if not is_available(stock):
            lines.append(f"    {i18n.t(lang, 'cart_item_unavailable')}")
        else:
            qty = min(item.quantity, stock.quantity)
            subtotal = stock.price * qty
            total += subtotal
            lines.append(f"    {qty} × {money(stock.price, lang)} = {money(subtotal, lang)}")
            if item.quantity > stock.quantity:
                lines.append(f"    {i18n.t(lang, 'cart_only_n', n=stock.quantity)}")
        lines.append("")
    lines.append(i18n.t(lang, "cart_total", total=money(total, lang)))
    return "\n".join(lines)[:4000]
