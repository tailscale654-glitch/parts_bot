"""Сотрудник дилера: «📋 Заказы дилера» — список и карточки заказов только своего дилера."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, User
from app.database.repositories.admin import ORDER_FILTERS, AdminRepository
from app.database.repositories.orders import OrderRepository
from app.keyboards.orders import admin_order_keyboard
from app.services.catalog import money, paginate
from app.services.localization import i18n
from app.services.notify import person_name
from app.services.orders import order_text, status_text

router = Router(name="dealer")
PAGE = 10


class DealerCB(CallbackData, prefix="dl"):
    section: str  # orders | order
    f: str = "all"
    page: int = 1
    id: int = 0


def _btn(text: str, **cb) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=DealerCB(**cb).pack())


async def dealer_orders_view(
    session: AsyncSession, dealer_id: int, lang: str | None, key: str = "new", page_no: int = 1,
) -> tuple[str, InlineKeyboardMarkup]:
    repo = AdminRepository(session)
    counts = await repo.order_counts(dealer_id=dealer_id)
    key = key if key in ORDER_FILTERS else "all"
    page = paginate(counts[key], page_no, PAGE)
    items, total = await repo.orders_page(key, page.offset, PAGE, dealer_id=dealer_id)
    dealer = await session.get(Dealer, dealer_id)
    lines = [i18n.t(lang, "dealer_orders_title", dealer=dealer.name, tab=i18n.t(lang, f"tab_{key}")), ""]
    lines.append(i18n.t(lang, "adm_shown", a=page.offset + 1, b=page.offset + len(items), total=total)
                 if items else i18n.t(lang, "adm_orders_empty"))

    def tab(k: str) -> InlineKeyboardButton:
        return _btn(f"{'• ' if k == key else ''}{i18n.t(lang, f'tab_{k}')} ({counts[k]})", section="orders", f=k)
    keys = list(ORDER_FILTERS)
    rows = [[tab(k) for k in keys[:2]], [tab(k) for k in keys[2:]]]
    for o in items:
        icon = status_text(o.status, lang).split(" ")[0]
        rows.append([_btn(f"№{o.id} · {icon} · {money(o.total_amount, lang)} · {person_name(o.user)}",
                          section="order", id=o.id, f=key, page=page.number)])
    if page.total_pages > 1:
        rows.append([
            _btn("◀️", section="orders", f=key, page=max(1, page.number - 1)),
            _btn(f"{page.number} / {page.total_pages}", section="orders", f=key, page=page.number),
            _btn("▶️", section="orders", f=key, page=min(page.total_pages, page.number + 1)),
        ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(text[:4000], reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(DealerCB.filter())
async def dealer_section(
    callback: CallbackQuery, callback_data: DealerCB, user: User, session: AsyncSession, staff_dealer_id: int | None,
) -> None:
    lang = user.language
    if staff_dealer_id is None:
        await callback.answer(i18n.t(lang, "not_staff"), show_alert=True)
        return
    if callback_data.section == "order":
        order = await OrderRepository(session).get(callback_data.id)
        if order is None or order.dealer_id != staff_dealer_id:  # только заказы своего дилера
            await callback.answer(i18n.t(lang, "chat_forbidden"), show_alert=True)
            return
        back = DealerCB(section="orders", f=callback_data.f, page=callback_data.page).pack()
        await _edit(callback, order_text(order, lang, for_admin=True), admin_order_keyboard(order, lang, back, staff=True))
        return
    await _edit(callback, *await dealer_orders_view(session, staff_dealer_id, lang, callback_data.f, callback_data.page))
