"""Логика каталога, не зависящая от Telegram: пагинация и текст карточки детали."""
import math
from dataclasses import dataclass
from urllib.parse import quote

from decimal import Decimal

from app.database.models import CartItem, Dealer, Part, Region, Stock
from app.database.repositories.cart import item_available
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
DEFAULT_PREORDER_DAYS = "3-5"  # если в «⚙️ Настройки → Регионы» срок не задан


def money(value: Decimal | int, lang: str | None) -> str:
    """85000 → «85 000 сум»."""
    value = Decimal(value)
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{text.replace(',', ' ')} {i18n.t(lang, 'currency')}"


def days_text(value: str | None, lang: str | None) -> str:
    """Срок предзаказа из настроек региона: «1-2» → «1–2 дня», «3» → «3 дня», «1» → «1 день»."""
    value = (value or DEFAULT_PREORDER_DAYS).replace("–", "-").replace(" ", "")
    numbers = [int(x) for x in value.split("-") if x.isdigit()] or [3]
    n = numbers[-1]
    if n % 10 == 1 and n % 100 != 11:
        form = "one"
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        form = "few"
    else:
        form = "many"
    return f"{'–'.join(map(str, numbers))} {i18n.t(lang, f'unit_day_{form}')}"


def region_days(region: Region | None, lang: str | None) -> str:
    return days_text(region.preorder_days if region is not None else None, lang)


@dataclass
class Preorder:
    """Деталь можно заказать со склада JAC: её привезут к одному из дилеров региона."""
    stock: Stock  # остаток на складе (цена, сколько штук)
    dealers: list[Dealer]  # у кого из дилеров региона можно забрать
    days: str  # «1–2 дня»


def map_url(dealer: Dealer) -> str | None:
    """Яндекс Карты: точка дилера (если задана в панели) или поиск по адресу. Нет ни того ни другого — None."""
    if dealer.latitude is not None and dealer.longitude is not None:
        return f"https://yandex.uz/maps/?pt={dealer.longitude},{dealer.latitude}&z=17&l=map"
    if dealer.address:
        return "https://yandex.uz/maps/?text=" + quote(f"{dealer.name}, {dealer.address}")
    return None


def dealer_lines(dealer: Dealer) -> list[str]:
    lines = [f"🏢 {dealer.name}"]
    if dealer.address:
        lines.append(f"📌 {dealer.address}")
    if dealer.phone:
        lines.append(f"📞 {dealer.phone}")
    return lines


def offer_lines(stock: Stock, lang: str | None) -> list[str]:
    lines = dealer_lines(stock.dealer)
    if stock.quantity > 0:
        lines.append(f"💰 {money(stock.price, lang)} · {i18n.t(lang, 'in_stock', n=stock.quantity)}")
    else:
        lines.append(f"💰 {money(stock.price, lang)}")
        lines.append(i18n.t(lang, "on_order", days=stock.delivery_days) if stock.delivery_days
                     else i18n.t(lang, "out_of_stock"))
    return lines


def part_head(part: Part, lang: str | None) -> list[str]:
    lines = [
        f"📦 {localized_name(part, lang).upper()}",
        f"🔢 {i18n.t(lang, 'part_number', number=part.part_number)}",
        f"🚗 {i18n.t(lang, 'part_model', model=localized_name(part.model, lang))}",
        f"🗂 {i18n.t(lang, 'part_node', node=localized_name(part.node, lang))}",
    ]
    description = getattr(part, f"description_{lang}", None) or part.description_ru
    if description:
        lines += ["", description]
    return lines


def part_card_text(
    part: Part, lang: str | None, region: Region | None = None,
    offers: list[Stock] | None = None, regions_elsewhere: int = 0, preorder: Preorder | None = None,
) -> str:
    """Простая карточка: лучшая цена в регионе (остальные дилеры — по кнопке «Все дилеры»)
    или, если у дилеров региона детали нет, — предзаказ со склада JAC."""
    lines = part_head(part, lang)
    if region is None:
        return "\n".join(lines)
    offers = [o for o in (offers or []) if o.quantity > 0]
    lines += ["", f"📍 {localized_name(region, lang).upper()}"]
    if offers:
        best = offers[0]
        lines.append(i18n.t(lang, "card_in_stock_many", n=len(offers), price=money(best.price, lang))
                     if len(offers) > 1 else i18n.t(lang, "card_in_stock_one"))
        lines += [""] + offer_lines(best, lang)
        if len(offers) > 1:
            lines.append(i18n.t(lang, "card_best_price"))
    elif preorder is not None:
        lines += [i18n.t(lang, "card_preorder_title"), "",
                  f"💰 {money(preorder.stock.price, lang)}",
                  i18n.t(lang, "card_preorder_days", days=preorder.days)]
        if len(preorder.dealers) == 1:
            lines += ["", i18n.t(lang, "card_preorder_pickup")] + dealer_lines(preorder.dealers[0])
        else:
            lines += ["", i18n.t(lang, "card_preorder_choose", n=len(preorder.dealers))]
    else:
        lines += ["", i18n.t(lang, "no_offers_in_region")]
        if regions_elsewhere:
            lines.append(i18n.t(lang, "offers_elsewhere", n=regions_elsewhere))
    return "\n".join(lines)


def offers_text(part: Part, lang: str | None, region: Region | None, offers: list[Stock]) -> str:
    """Экран «🏢 Все дилеры»: все дилеры региона, у которых деталь есть, — дешевле выше."""
    lines = [f"📦 {localized_name(part, lang).upper()}", f"🔢 {i18n.t(lang, 'part_number', number=part.part_number)}"]
    if region is not None:
        lines += ["", f"📍 {localized_name(region, lang).upper()}"]
    for stock in offers[:MAX_OFFERS_SHOWN]:
        lines += [""] + offer_lines(stock, lang)
    if len(offers) > MAX_OFFERS_SHOWN:
        lines += ["", i18n.t(lang, "more_dealers", n=len(offers) - MAX_OFFERS_SHOWN)]
    return "\n".join(lines)


def pickup_text(part: Part, lang: str | None, preorder: Preorder) -> str:
    """Предзаказ: «Где заберёте деталь?» — список дилеров региона."""
    return i18n.t(lang, "preorder_pick_title", name=localized_name(part, lang),
                  price=money(preorder.stock.price, lang), days=preorder.days)


def item_line(item: CartItem, lang: str | None) -> str:
    """Где клиент заберёт позицию корзины: «🏢 Дилер» или «🚚 Под заказ → 🏢 Дилер · 1–2 дня»."""
    if item.stock.dealer.is_warehouse:
        dealer = item.pickup_dealer
        return i18n.t(lang, "cart_preorder_line", dealer=dealer.name if dealer else "—",
                      days=region_days(dealer.region if dealer else None, lang))
    return f"🏢 {item.stock.dealer.name}"


def cart_text(items: list[CartItem], lang: str | None) -> str:
    lines = [i18n.t(lang, "cart_title"), ""]
    total = Decimal(0)
    for n, item in enumerate(items, start=1):
        stock = item.stock
        part = stock.part
        lines.append(f"{n}. {localized_name(part, lang)} ({part.part_number})")
        lines.append(f"    {item_line(item, lang)}")
        if not item_available(item):
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
