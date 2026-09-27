from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.repositories.admin import ORDER_FILTERS
from app.services.catalog import Page
from app.services.localization import i18n


class AdminCB(CallbackData, prefix="ap"):
    section: str  # menu | orders | order | search | dealers | dealer | toggle | catalog | clients | client | stats | export
    f: str = ""  # вкладка заказов: new | work | done | cancel | all
    page: int = 1
    id: int = 0


def btn(text: str, **cb) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=AdminCB(**cb).pack())


def menu_button(lang: str) -> list[InlineKeyboardButton]:
    return [btn(i18n.t(lang, "btn_adm_menu"), section="menu")]


def pager(section: str, page: Page, **extra) -> list[InlineKeyboardButton]:
    if page.total_pages <= 1:
        return []
    noop = AdminCB(section="noop").pack()
    return [
        btn("◀️", section=section, page=page.number - 1, **extra) if page.has_prev else InlineKeyboardButton(text="·", callback_data=noop),
        InlineKeyboardButton(text=f"{page.number} / {page.total_pages}", callback_data=noop),
        btn("▶️", section=section, page=page.number + 1, **extra) if page.has_next else InlineKeyboardButton(text="·", callback_data=noop),
    ]


def admin_menu_keyboard(lang: str, new_orders: int) -> InlineKeyboardMarkup:
    orders_text = i18n.t(lang, "btn_adm_orders_new", n=new_orders) if new_orders else i18n.t(lang, "btn_adm_orders")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(orders_text, section="orders", f="new" if new_orders else "all")],
        [btn(i18n.t(lang, "btn_adm_dealers"), section="dealers"), btn(i18n.t(lang, "btn_adm_catalog"), section="catalog")],
        [btn(i18n.t(lang, "btn_adm_stats"), section="stats", f="today"), btn(i18n.t(lang, "btn_adm_clients"), section="clients")],
        [InlineKeyboardButton(text=i18n.t(lang, "btn_upload_excel"), callback_data="adm:upload"),
         InlineKeyboardButton(text=i18n.t(lang, "btn_template"), callback_data="adm:template")],
        [btn(i18n.t(lang, "btn_adm_backup"), section="backup")],
    ])


def order_tabs(lang: str, counts: dict[str, int], active: str) -> list[list[InlineKeyboardButton]]:
    def tab(key: str) -> InlineKeyboardButton:
        mark = "• " if key == active else ""
        return btn(f"{mark}{i18n.t(lang, f'tab_{key}')} ({counts.get(key, 0)})", section="orders", f=key)
    keys = list(ORDER_FILTERS)
    return [[tab(k) for k in keys[:2]], [tab(k) for k in keys[2:]]]
