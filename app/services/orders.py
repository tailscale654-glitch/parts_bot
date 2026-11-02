"""Тексты заказов для покупателя и администратора."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.database.models import CartItem, Order, OrderItem
from app.database.repositories.cart import item_available
from app.database.repositories.orders import StockProblem
from app.services.catalog import money, region_days
from app.services.localization import i18n, localized_name

TIMEZONE = ZoneInfo("Asia/Tashkent")


def set_timezone(name: str) -> None:
    global TIMEZONE
    TIMEZONE = ZoneInfo(name)


def fmt_date(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:  # SQLite в тестах хранит без часового пояса (UTC)
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(TIMEZONE).strftime("%d.%m.%Y %H:%M")


def status_text(status: str, lang: str | None, preorder: bool = False) -> str:
    """Предзаказ «Подтверждён» = деталь уже едет со склада к дилеру — так и пишем."""
    if preorder and status == "CONFIRMED":
        return i18n.t(lang, "status_CONFIRMED_preorder")
    return i18n.t(lang, f"status_{status}")


def order_status(order: Order, lang: str | None) -> str:
    return status_text(order.status, lang, order.preorder)


PROGRESS = ("NEW", "CONFIRMED", "READY", "COMPLETED")


def progress_lines(order: Order, lang: str | None) -> list[str]:
    """Шкала заказа: ✅ пройдено, ⏳ сейчас, ▫️ впереди. Отменённый заказ — без шкалы."""
    if order.status not in PROGRESS:
        return []
    now = PROGRESS.index(order.status)
    lines = []
    for i, step in enumerate(PROGRESS):
        mark = "✅" if i <= now else "⏳" if i == now + 1 else "▫️"
        key = f"progress_{step}_preorder" if order.preorder and step == "CONFIRMED" else f"progress_{step}"
        lines.append(f"{mark} {i18n.t(lang, key)}")
    return lines


def item_name(item: OrderItem, lang: str | None) -> str:
    return localized_name(item, lang)


def checkout_preview_text(items: list[CartItem], lang: str | None) -> str:
    """Экран «Проверьте заказ»: позиции по дилерам и сумма каждого будущего заказа."""
    groups: dict[tuple[int, bool], list[CartItem]] = {}
    for item in items:
        if item_available(item):
            groups.setdefault((item.dealer.id, item.stock.dealer.is_warehouse), []).append(item)
    lines = [i18n.t(lang, "checkout_title"), ""]
    grand = 0
    for (_, preorder), dealer_items in groups.items():
        dealer = dealer_items[0].dealer
        lines.append(f"🏢 {dealer.name}")
        if preorder:
            lines.append(i18n.t(lang, "checkout_preorder", days=region_days(dealer.region, lang)))
        subtotal = 0
        for item in dealer_items:
            s = item.stock
            total = s.price * item.quantity
            subtotal += total
            lines.append(f"• {localized_name(s.part, lang)} ({s.part.part_number}) — {item.quantity} × {money(s.price, lang)}")
        lines.append(i18n.t(lang, "checkout_dealer_total", total=money(subtotal, lang)))
        lines.append("")
        grand += subtotal
    if len(groups) > 1:
        lines.append(i18n.t(lang, "checkout_split", n=len(groups)))
    lines.append(i18n.t(lang, "cart_total", total=money(grand, lang)))
    lines += ["", i18n.t(lang, "checkout_confirm_hint")]
    return "\n".join(lines)[:4000]


def stock_problems_text(problems: list[StockProblem], lang: str | None) -> str:
    lines = [i18n.t(lang, "checkout_stock_changed"), ""]
    for p in problems:
        name = (p.names.get(lang) if lang else None) or p.names["ru"]
        key = "checkout_now_n" if p.available else "checkout_now_none"
        lines.append(f"• {name} — {i18n.t(lang, key, n=p.available, want=p.wanted)}")
    lines += ["", i18n.t(lang, "checkout_fix_cart")]
    return "\n".join(lines)


def order_text(order: Order, lang: str | None, for_admin: bool = False) -> str:
    """Карточка заказа. Для админа — ещё клиент, телефон, регион, модель и категория."""
    dealer = order.dealer
    title = i18n.t(lang, "admin_new_order" if for_admin and order.status == "NEW" else "order_title", id=order.id)
    lines = [title, f"🕒 {fmt_date(order.created_at)}", ""]
    if order.preorder and for_admin:  # складу JAC: что и куда отправить
        source = order.source_dealer.name if order.source_dealer else "—"
        lines += [i18n.t(lang, "order_preorder_admin", source=source, dealer=dealer.name,
                         days=region_days(dealer.region, lang)), ""]
    if for_admin:
        user = order.user
        name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
        if user.username:
            name += f" (@{user.username})"
        region = localized_name(user.region, lang) if user.region else "—"
        lines += [
            i18n.t(lang, "order_client", name=name),
            i18n.t(lang, "order_phone", phone=user.phone or "—"),
            i18n.t(lang, "order_client_region", region=region),
        ]
        if order.car:
            lines.append(i18n.t(lang, "order_car", car=order.car))
        lines.append("")
    for n, item in enumerate(order.items, start=1):
        lines.append(f"{n}. 📦 {item_name(item, lang)}")
        lines.append(f"    {i18n.t(lang, 'part_number', number=item.part_number)}")
        if for_admin and item.model_name:
            lines.append(f"    🚗 {item.model_name} · 🔧 {item.node_name}")
        lines.append(f"    {item.quantity} × {money(item.price, lang)} = {money(item.total, lang)}")
    lines += [
        "",
        i18n.t(lang, "order_total", total=money(order.total_amount, lang)),
        "",
        f"🏢 {dealer.name}",
    ]
    if dealer.address:
        lines.append(f"📌 {dealer.address}")
    if dealer.phone:
        lines.append(f"📞 {dealer.phone}")
    if order.preorder and not for_admin and order.status in ("NEW", "CONFIRMED"):
        lines += ["", i18n.t(lang, "order_preorder_client", days=region_days(dealer.region, lang))]
    lines += ["", order_status(order, lang)]
    progress = progress_lines(order, lang)
    if progress:
        lines += [""] + progress
    return "\n".join(lines)[:4000]


def order_line(order: Order, lang: str | None) -> str:
    """Одна строка в списке «Мои заказы»."""
    mark = "🚚 " if order.preorder else ""
    return f"{mark}№{order.id} · {fmt_date(order.created_at)[:10]} · {money(order.total_amount, lang)} · {order_status(order, lang)}"
