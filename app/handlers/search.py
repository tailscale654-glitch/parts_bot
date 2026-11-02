"""🔎 Поиск: нажали кнопку меню — следующий текст ищем по названию и артикулу.
Клиент ищет среди деталей для своего автомобиля (+ «Прочее»), сотрудник дилера — по всем моделям.
Ничего не нашлось — одной кнопкой отправляем запрос менеджеру (в «💬 Чат» веб-панели)."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import User
from app.database.repositories.catalog import CatalogRepository
from app.handlers.catalog import _show, full_access
from app.keyboards.catalog import SearchCB, search_nothing_keyboard, search_results_keyboard
from app.keyboards.main import menu_action
from app.services import cars, support
from app.services.import_mapping import ALL_MODELS
from app.services.localization import i18n
from app.services.search import norm
from app.states.search import SearchStates

router = Router(name="search")
MAX_RESULTS = 20


def search_prompt(user: User, full: bool) -> str:
    lang = user.language
    scope = i18n.t(lang, "search_scope_all") if full else i18n.t(
        lang, "search_scope_car", car=cars.car_text(user, lang) or i18n.t(lang, "car_not_selected"))
    return i18n.t(lang, "search_prompt", scope=scope)


async def start_search(message: Message, user: User, state: FSMContext, full: bool) -> None:
    """Кнопка «🔎 Поиск» в нижнем меню (вызывается из handlers/start.py)."""
    await state.set_state(SearchStates.query)
    await message.answer(search_prompt(user, full))


async def search_view(user: User, session: AsyncSession, query: str, full: bool) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    repo = CatalogRepository(session, user.region_id)
    models = None if full else {cars.catalog_model(user), ALL_MODELS[0]}
    parts = await repo.search(query, lang, models, limit=MAX_RESULTS + 1)
    if not parts:
        return i18n.t(lang, "search_nothing", q=query), search_nothing_keyboard(lang)
    shown = parts[:MAX_RESULTS]
    local = await repo.with_local_stock([p.id for p in shown])
    text = i18n.t(lang, "search_found", q=query, n=len(shown) if len(parts) <= MAX_RESULTS else f"{MAX_RESULTS}+")
    if len(local) < len(shown):
        text += "\n" + i18n.t(lang, "search_legend")
    if len(parts) > MAX_RESULTS:
        text += "\n\n" + i18n.t(lang, "search_more", n=MAX_RESULTS)
    return text, search_results_keyboard(shown, lang, local)


@router.message(SearchStates.query, F.text, ~F.text.func(menu_action), ~F.text.startswith("/"))
async def do_search(message: Message, user: User, session: AsyncSession, state: FSMContext,
                    settings: Settings | None = None, staff_dealer_id: int | None = None) -> None:
    query = " ".join(message.text.split())[:64]
    if len(norm(query).replace(" ", "")) < 2:
        await message.answer(i18n.t(user.language, "search_short"))
        return
    await state.update_data(search_q=query)  # для «◀️ К результатам» из карточки детали
    text, kb = await search_view(user, session, query, full_access(user, settings, staff_dealer_id))
    await message.answer(text, reply_markup=kb)


@router.callback_query(SearchCB.filter(F.action == "results"))
async def back_to_results(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext,
                          settings: Settings | None = None, staff_dealer_id: int | None = None) -> None:
    full = full_access(user, settings, staff_dealer_id)
    query = (await state.get_data()).get("search_q")
    await state.set_state(SearchStates.query)  # можно сразу писать новый запрос
    if not query:  # бот перезапускался — запрос не сохранился
        await _show(callback, search_prompt(user, full), None)
        return
    text, kb = await search_view(user, session, query, full)
    await _show(callback, text, kb)


@router.callback_query(SearchCB.filter(F.action == "manager"))
async def ask_manager(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext,
                      bot: Bot, settings: Settings) -> None:
    """Не нашёл — запрос уходит менеджерам в «💬 Чат». Дальше клиент пишет как обычно — в тот же чат."""
    from app.handlers.support import notify_staff

    lang = user.language
    query = (await state.get_data()).get("search_q") or "—"
    await state.set_state(None)  # следующий текст — уже менеджеру, а не в поиск
    got = await support.add_incoming(session, user, i18n.t("ru", "search_manager_note", q=query))
    await _show(callback, i18n.t(lang, "search_sent", q=query), None)
    await notify_staff(bot, settings, session, got)
