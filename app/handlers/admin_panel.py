"""Админ-панель: заказы, дилеры, каталог, клиенты. Только для ADMIN_IDS."""
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from pathlib import Path

from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.admin import ORDER_FILTERS, AdminRepository
from app.database.repositories.orders import OrderRepository
from app.database.repositories.staff import StaffRepository
from app.database.repositories.stats import PERIODS, StatsRepository, period_start
from app.keyboards.admin import AdminCB, admin_menu_keyboard, btn, menu_button, order_tabs, pager
from app.keyboards.orders import admin_order_keyboard
from app.services.catalog import money, paginate
from app.services.localization import i18n, localized_name
from app.services.notify import person_name, send
from app.services import orders as orders_service
from app.services.orders import fmt_date, order_text, status_text
from app.services.stats import export_filename, orders_excel, orders_with_items_text, stats_text
from app.states.admin import AdminStates
from app.utils.filters import IsAdmin

router = Router(name="admin_panel")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE = 10


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(text[:4000], reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def _name(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or (f"@{user.username}" if user.username else "—")


# ---------- меню ----------

async def admin_menu_view(session: AsyncSession, lang: str | None) -> tuple[str, InlineKeyboardMarkup]:
    counts = await AdminRepository(session).order_counts()
    text = i18n.t(lang, "admin_menu")
    if counts["new"]:
        text += "\n\n" + i18n.t(lang, "admin_menu_new", n=counts["new"])
    return text, admin_menu_keyboard(lang, counts["new"])


@router.callback_query(AdminCB.filter(F.section == "menu"))
async def show_menu(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _edit(callback, *await admin_menu_view(session, user.language))


@router.callback_query(AdminCB.filter(F.section == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ---------- заказы ----------

def order_button_text(order, lang) -> str:
    icon = status_text(order.status, lang).split(" ")[0]
    return f"№{order.id} · {icon} · {money(order.total_amount, lang)} · {_name(order.user)}"


@router.callback_query(AdminCB.filter(F.section == "orders"))
async def orders(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    key = callback_data.f if callback_data.f in ORDER_FILTERS else "all"
    repo = AdminRepository(session)
    counts = await repo.order_counts()
    page = paginate(counts[key], callback_data.page, PAGE)
    items, total = await repo.orders_page(key, page.offset, PAGE)
    lines = [i18n.t(lang, "adm_orders_title", tab=i18n.t(lang, f"tab_{key}")), ""]
    if items:
        lines.append(i18n.t(lang, "adm_shown", a=page.offset + 1, b=page.offset + len(items), total=total))
    else:
        lines.append(i18n.t(lang, "adm_orders_empty"))
    rows = order_tabs(lang, counts, key)
    rows += [[btn(order_button_text(o, lang), section="order", id=o.id, f=key, page=page.number)] for o in items]
    nav = pager("orders", page, f=key)
    if nav:
        rows.append(nav)
    rows.append([btn(i18n.t(lang, "btn_adm_search"), section="search")] + menu_button(lang))
    await _edit(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminCB.filter(F.section == "order"))
async def order(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    order = await OrderRepository(session).get(callback_data.id)
    if order is None:
        await callback.answer(i18n.t(lang, "adm_not_found"), show_alert=True)
        return
    back = AdminCB(section="orders", f=callback_data.f or "all", page=callback_data.page).pack()
    await _edit(callback, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang, back))


@router.callback_query(AdminCB.filter(F.section == "search"))
async def search_ask(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(AdminStates.search_order)
    await callback.answer()
    await callback.message.answer(i18n.t(user.language, "adm_search_ask"))


@router.message(AdminStates.search_order, F.text)
async def search_order(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    lang = user.language
    number = message.text.strip().lstrip("№#")
    if not number.isdigit():
        await message.answer(i18n.t(lang, "adm_search_bad"))
        return
    await state.clear()
    order = await OrderRepository(session).get(int(number))
    if order is None:
        await message.answer(i18n.t(lang, "adm_not_found"))
        return
    await message.answer(order_text(order, lang, for_admin=True), reply_markup=admin_order_keyboard(order, lang))


# ---------- дилеры ----------

@router.callback_query(AdminCB.filter(F.section == "dealers"))
async def dealers(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    repo = AdminRepository(session)
    _, total = await repo.dealers_page(0, 1)
    page = paginate(total, callback_data.page, PAGE)
    rows_data, _ = await repo.dealers_page(page.offset, PAGE)
    lines = [i18n.t(lang, "adm_dealers_title")]
    region = None
    for r in rows_data:
        if r.dealer.region_id != region:
            region = r.dealer.region_id
            lines += ["", f"📍 {localized_name(r.dealer.region, lang)}"]
        icon = "🟢" if r.dealer.enabled and r.offers else ("⛔" if not r.dealer.enabled else "⚪")
        lines.append(i18n.t(lang, "adm_dealer_line", icon=icon, name=r.dealer.name, offers=r.offers, orders=r.orders))
    if total > PAGE:
        lines += ["", i18n.t(lang, "adm_shown", a=page.offset + 1, b=page.offset + len(rows_data), total=total)]
    rows = [[btn(r.dealer.name, section="dealer", id=r.dealer.id, page=page.number)] for r in rows_data]
    nav = pager("dealers", page)
    if nav:
        rows.append(nav)
    rows.append(menu_button(lang))
    await _edit(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


async def _dealer_card(callback: CallbackQuery, dealer_id: int, page: int, lang, session: AsyncSession) -> None:
    row = await AdminRepository(session).dealer(dealer_id)
    if row is None:
        await callback.answer(i18n.t(lang, "adm_not_found"), show_alert=True)
        return
    d = row.dealer
    yes, no = i18n.t(lang, "yes"), i18n.t(lang, "no")
    text = i18n.t(
        lang, "adm_dealer_card",
        name=d.name, code=d.code or "—", region=localized_name(d.region, lang), address=d.address or "—",
        phone=d.phone or "—", visible=i18n.t(lang, "visible_yes" if d.enabled else "visible_no"),
        active=yes if d.active else no, directory=yes if d.in_directory else no, offers=row.offers, orders=row.orders,
    )
    if d.in_directory:
        text += "\n\n" + i18n.t(lang, "adm_dealer_note")
    toggle = i18n.t(lang, "btn_dealer_hide" if d.enabled else "btn_dealer_show")
    staff_count = len(await StaffRepository(session).staff_of(d.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn(i18n.t(lang, "btn_invite_staff"), section="invite", id=d.id, page=page),
         btn(i18n.t(lang, "btn_staff_list", n=staff_count), section="staff", id=d.id, page=page)],
        [btn(toggle, section="toggle", id=d.id, page=page)],
        [btn(i18n.t(lang, "btn_back"), section="dealers", page=page)],
    ])
    await _edit(callback, text, kb)


@router.callback_query(AdminCB.filter(F.section == "dealer"))
async def dealer(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    await _dealer_card(callback, callback_data.id, callback_data.page, user.language, session)


@router.callback_query(AdminCB.filter(F.section == "toggle"))
async def toggle_dealer(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    dealer = await AdminRepository(session).toggle_dealer(callback_data.id)
    if dealer is not None:
        await callback.answer(i18n.t(user.language, "dealer_shown" if dealer.enabled else "dealer_hidden"))
    await _dealer_card(callback, callback_data.id, callback_data.page, user.language, session)


@router.callback_query(AdminCB.filter(F.section == "invite"))
async def invite(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession, bot: Bot) -> None:
    lang = user.language
    row = await AdminRepository(session).dealer(callback_data.id)
    if row is None:
        await callback.answer(i18n.t(lang, "adm_not_found"), show_alert=True)
        return
    token = await StaffRepository(session).create_invite(row.dealer.id)
    link = f"https://t.me/{(await bot.me()).username}?start=dealer_{token}"
    await callback.answer()
    # отдельным сообщением — чтобы его было удобно переслать
    await callback.message.answer(i18n.t(lang, "invite_created", dealer=row.dealer.name, link=link))


async def _staff_view(callback: CallbackQuery, dealer_id: int, page: int, lang, session: AsyncSession) -> None:
    row = await AdminRepository(session).dealer(dealer_id)
    if row is None:
        await callback.answer(i18n.t(lang, "adm_not_found"), show_alert=True)
        return
    staff = await StaffRepository(session).staff_of(dealer_id)
    lines = [i18n.t(lang, "staff_title", dealer=row.dealer.name), ""]
    lines += [i18n.t(lang, "staff_line", name=person_name(s.user), phone=s.user.phone or "—") for s in staff] or [
        i18n.t(lang, "staff_empty")]
    rows = [[btn(i18n.t(lang, "btn_staff_remove", name=person_name(s.user)), section="unstaff", id=s.id, page=page)]
            for s in staff]
    rows.append([btn(i18n.t(lang, "btn_invite_staff"), section="invite", id=dealer_id, page=page)])
    rows.append([btn(i18n.t(lang, "btn_back"), section="dealer", id=dealer_id, page=page)])
    await _edit(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminCB.filter(F.section == "staff"))
async def staff_list(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    await _staff_view(callback, callback_data.id, callback_data.page, user.language, session)


@router.callback_query(AdminCB.filter(F.section == "unstaff"))
async def staff_remove(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession, bot: Bot) -> None:
    removed = await StaffRepository(session).remove(callback_data.id)
    if removed is None:
        await callback.answer(i18n.t(user.language, "adm_not_found"), show_alert=True)
        return
    await send(bot, removed.user.telegram_id,
               i18n.t(removed.user.language, "staff_removed_notice", dealer=removed.dealer.name))
    await callback.answer(i18n.t(user.language, "staff_removed"))
    await _staff_view(callback, removed.dealer_id, callback_data.page, user.language, session)


# ---------- статистика ----------

@router.callback_query(AdminCB.filter(F.section == "stats"))
async def stats(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    period = callback_data.f if callback_data.f in PERIODS else "today"
    repo = StatsRepository(session)
    since = period_start(period, orders_service.TIMEZONE)
    data = await repo.collect(since)
    recent, _ = await repo.orders_page(since, 0, 5)  # последние 5 заказов с составом
    tabs = [btn(("• " if p == period else "") + i18n.t(lang, f"period_{p}"), section="stats", f=p) for p in PERIODS]
    rows = [tabs[:2], tabs[2:]]
    if data.orders:
        rows.append([btn(i18n.t(lang, "btn_stats_orders"), section="sorders", f=period)])
    rows += [[btn(i18n.t(lang, "btn_export_excel"), section="export", f=period)], menu_button(lang)]
    await _edit(callback, stats_text(data, period, lang, recent), InlineKeyboardMarkup(inline_keyboard=rows))


STATS_PAGE = 5


@router.callback_query(AdminCB.filter(F.section == "sorders"))
async def stats_orders(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    """Все заказы периода с составом, по 5 на странице."""
    lang = user.language
    period = callback_data.f if callback_data.f in PERIODS else "all"
    since = period_start(period, orders_service.TIMEZONE)
    repo = StatsRepository(session)
    _, total = await repo.orders_page(since, 0, 1)
    page = paginate(total, callback_data.page, STATS_PAGE)
    items, _ = await repo.orders_page(since, page.offset, STATS_PAGE)
    shown = i18n.t(lang, "adm_shown", a=page.offset + 1, b=page.offset + len(items), total=total) if items else i18n.t(lang, "stats_no_orders")
    title = i18n.t(lang, "stats_orders_title", period=i18n.t(lang, f"period_{period}"), shown=shown)
    rows = []
    nav = pager("sorders", page, f=period)
    if nav:
        rows.append(nav)
    rows.append([btn(i18n.t(lang, "btn_back"), section="stats", f=period)])
    await _edit(callback, orders_with_items_text(items, lang, title), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminCB.filter(F.section == "export"))
async def export(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    period = callback_data.f if callback_data.f in PERIODS else "all"
    items = await StatsRepository(session).orders_for_export(period_start(period, orders_service.TIMEZONE))
    if not items:
        await callback.answer(i18n.t(lang, "export_empty"), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(orders_excel(items, lang), filename=export_filename(period)),
        caption=i18n.t(lang, "export_caption", period=i18n.t(lang, f"period_{period}"), n=len(items)),
    )


# ---------- резервная копия ----------

BACKUP_DIR = Path("/bot/backups")  # в docker-compose сюда подключена папка ./backups (только чтение)
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


def latest_backup(directory: Path = BACKUP_DIR) -> Path | None:
    files = sorted(directory.glob("jac_parts_*.sql.gz")) if directory.exists() else []
    return files[-1] if files else None  # имена с датой — последняя по алфавиту = самая новая


@router.callback_query(AdminCB.filter(F.section == "backup"))
async def send_backup(callback: CallbackQuery, user: User) -> None:
    lang = user.language
    path = latest_backup()
    if path is None:
        await callback.answer(i18n.t(lang, "backup_none"), show_alert=True)
        return
    size = path.stat().st_size
    if size > TELEGRAM_FILE_LIMIT:
        await callback.answer(i18n.t(lang, "backup_too_big"), show_alert=True)
        return
    date = path.stem.removeprefix("jac_parts_").removesuffix(".sql").replace("_", " ")
    await callback.answer()
    await callback.message.answer_document(
        FSInputFile(path), caption=i18n.t(lang, "backup_caption", date=date, size=f"{size / 1024:.0f} КБ"))


# ---------- каталог ----------

@router.callback_query(AdminCB.filter(F.section == "catalog"))
async def catalog(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    lang = user.language
    s = await AdminRepository(session).catalog_summary()
    lines = [i18n.t(lang, "adm_catalog", active=s.parts_active, hidden=s.parts_hidden,
                    offers=s.offers_in_stock, dealers=s.dealers_with_stock)]
    if s.by_model:
        lines += ["", i18n.t(lang, "adm_catalog_models")] + [f"• {name}: {n}" for name, n in s.by_model]
    if s.by_node:
        lines += ["", i18n.t(lang, "adm_catalog_nodes")] + [f"• {name}: {n}" for name, n in s.by_node]
    await _edit(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[menu_button(lang)]))


# ---------- клиенты ----------

@router.callback_query(AdminCB.filter(F.section == "clients"))
async def clients(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    repo = AdminRepository(session)
    started, registered = await repo.clients_total()
    page = paginate(registered, callback_data.page, PAGE)
    rows_data, _ = await repo.clients_page(page.offset, PAGE)
    lines = [i18n.t(lang, "adm_clients_title", total=started, registered=registered), ""]
    for r in rows_data:
        region = localized_name(r.user.region, lang) if r.user.region else "—"
        lines.append(i18n.t(lang, "adm_client_line", name=_name(r.user), phone=r.user.phone, region=region,
                            orders=r.orders, spent=money(r.spent, lang)))
    rows = [[btn(f"{_name(r.user)} · {r.user.phone}", section="client", id=r.user.id, page=page.number)] for r in rows_data]
    nav = pager("clients", page)
    if nav:
        rows.append(nav)
    rows.append(menu_button(lang))
    await _edit(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminCB.filter(F.section == "client"))
async def client(callback: CallbackQuery, callback_data: AdminCB, user: User, session: AsyncSession) -> None:
    lang = user.language
    repo = AdminRepository(session)
    client_user = await repo.client(callback_data.id)
    if client_user is None:
        await callback.answer(i18n.t(lang, "adm_not_found"), show_alert=True)
        return
    orders, total = await repo.orders_page("all", 0, PAGE, user_id=client_user.id)
    spent = sum((o.total_amount for o in orders if o.status != "CANCELLED"), start=0)
    text = i18n.t(
        lang, "adm_client_card", name=_name(client_user), phone=client_user.phone or "—",
        region=localized_name(client_user.region, lang) if client_user.region else "—",
        language=i18n.t(client_user.language, "language_name"), since=fmt_date(client_user.created_at)[:10],
        orders=total, spent=money(spent, lang),
    )
    rows = [[btn(order_button_text(o, lang), section="order", id=o.id, f="all")] for o in orders]
    rows.append([btn(i18n.t(lang, "btn_back"), section="clients", page=callback_data.page)])
    await _edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
