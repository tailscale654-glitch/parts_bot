"""Веб-панель управления ботом (только локальная сеть компании).

Запуск (docker-compose, сервис web):
    uvicorn --factory app.panel.server:create_app --host 0.0.0.0 --port 8080
Вход: логин и пароль присылает бот — /panel (или приглашение от администратора).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from urllib.parse import urlencode

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, load_settings
from app.database.database import create_engine, create_session_factory
from app.database.models import (
    AuditLog,
    Broadcast,
    Dealer,
    DealerStaff,
    OrderMessage,
    Part,
    Region,
    User,
    WebUser,
)
from app.database.repositories.admin import ORDER_FILTERS, AdminRepository
from app.database.repositories.orders import TRANSITIONS, OrderRepository
from app.database.repositories.panel import OrderFilters, PanelRepository
from app.database.repositories.staff import StaffRepository
from app.database.repositories.stats import StatsRepository, period_start
from app.database.repositories.web_users import WebUserRepository
from app.keyboards.orders import reply_keyboard
from app.panel.charts import bar_chart
from app.services import audit, bot_settings, import_flow
from app.services import broadcast as broadcast_service
from app.services import orders as orders_service
from app.services.catalog import money, paginate
from app.services.excel_import import MAX_FILE_MB
from app.services.localization import i18n, localized_name
from app.services.notify import notify_status_change, person_name, send
from app.services.orders import fmt_date, status_text
from app.services.roles import ROLE_HINTS, ROLES, can
from app.services.stats import orders_excel

logger = logging.getLogger("jac_parts_panel")
HERE = Path(__file__).resolve().parent
LANG = "ru"  # язык панели
BRAND = os.getenv("PANEL_NAME", "JAC Motors Parts")  # название в шапке, на входе и во вкладке браузера
PAGE = 50
UPLOAD_DIR = Path(os.getenv("PANEL_UPLOAD_DIR", "/tmp/jac_imports"))  # файлы до «Применить»
STATUS_ORDER = ["CONFIRMED", "READY", "COMPLETED", "CANCELLED"]

templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(
    money=lambda v: money(v, LANG), fmt_date=fmt_date,
    status_text=lambda s: status_text(s, LANG).split(" —")[0],
    localized=lambda obj: localized_name(obj, LANG) if obj is not None else "—",
    person_name=person_name, tabs=[(k, i18n.t(LANG, f"tab_{k}")) for k in ORDER_FILTERS],
    ROLES=ROLES, ROLE_HINTS=ROLE_HINTS, brand=BRAND,
    # «JAC Motors Parts» → «JAC <span>Motors Parts</span>» (второе и дальше слова — акцентным цветом)
    brand_html=(lambda w: f"{w[0]} <span>{' '.join(w[1:])}</span>" if len(w) > 1 else w[0])(
        __import__("html").escape(BRAND).split()),
)


# ---------- запуск ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    orders_service.set_timezone(settings.timezone)
    engine = None
    if getattr(app.state, "session_factory", None) is None:  # в тестах подставляется своя база
        engine = create_engine(settings.database_url)
        app.state.session_factory = create_session_factory(engine)
    if getattr(app.state, "bot", None) is None:
        app.state.bot = Bot(token=settings.bot_token)  # только для отправки уведомлений, без polling
    try:
        async with app.state.session_factory() as session:
            await broadcast_service.mark_interrupted(session)  # рассылки, оборванные перезапуском
    except Exception:  # база ещё не готова — не мешаем запуску
        logger.exception("Cannot check unfinished broadcasts")
    yield
    for task in list(app.state.tasks):
        task.cancel()
    await app.state.bot.session.close()
    if engine is not None:
        await engine.dispose()


def create_app(settings: Settings | None = None, session_factory=None, bot: Bot | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app = FastAPI(title=BRAND, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.session_factory, app.state.bot = settings, session_factory, bot
    app.state.tasks = set()  # фоновые рассылки
    # Ключ подписи cookie: WEB_SECRET из .env, иначе выводится из токена бота (не меняется между перезапусками)
    secret = os.getenv("WEB_SECRET") or hashlib.sha256(f"panel:{settings.bot_token}".encode()).hexdigest()
    app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie="jac_panel",
                       max_age=12 * 3600, same_site="strict", https_only=os.getenv("WEB_HTTPS") == "1")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    register_routes(app)
    return app


# ---------- вход и права ----------

class LoginRequired(Exception):
    pass


class LoginThrottle:
    """Не больше 5 неудачных попыток входа за 5 минут с одного адреса."""

    def __init__(self, limit: int = 5, window: int = 300):
        self.limit, self.window = limit, window
        self.fails: dict[str, list[float]] = {}

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        self.fails[key] = [t for t in self.fails.get(key, []) if now - t < self.window]
        return len(self.fails[key]) >= self.limit

    def fail(self, key: str) -> None:
        self.fails.setdefault(key, []).append(time.monotonic())

    def reset(self, key: str) -> None:
        self.fails.pop(key, None)


throttle = LoginThrottle()


def role_of(web: WebUser, settings: Settings) -> str:
    """Люди из ADMIN_IDS (.env) — всегда администраторы."""
    return "admin" if web.user.telegram_id in settings.admin_ids else web.role


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


async def current_web(request: Request, session: AsyncSession = Depends(get_session)) -> WebUser:
    """Вход выполнен, сотрудник активен, пароль с тех пор не меняли (иначе — на страницу входа)."""
    wid, ver = request.session.get("wid"), request.session.get("ver")
    web = await WebUserRepository(session).get(wid) if wid else None
    if web is None or not web.active or web.session_version != ver:
        request.session.clear()
        raise LoginRequired()
    web.effective_role = role_of(web, request.app.state.settings)
    return web


def require(permission: str):
    async def checker(web: WebUser = Depends(current_web)) -> WebUser:
        if not can(web.effective_role, permission):
            raise HTTPException(403, "Недостаточно прав для этого действия.")
        return web
    return checker


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def check_csrf(request: Request, token: str) -> None:
    if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(400, "Форма устарела — обновите страницу и попробуйте снова.")


def render(request: Request, name: str, web: WebUser | None = None, **context) -> HTMLResponse:
    role = getattr(web, "effective_role", None)
    return templates.TemplateResponse(request, name, {
        "me": web, "role": role, "can": lambda p: can(role, p), "csrf": csrf_token(request),
        "flash": request.query_params.get("flash", ""), "path": request.url.path, **context,
    })


def back(url: str, flash: str) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}{urlencode({'flash': flash})}", status_code=303)


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


async def bot_username(request: Request) -> str | None:
    """Имя бота для ссылок-приглашений: BOT_USERNAME из .env, иначе спрашиваем у Telegram."""
    username = os.getenv("BOT_USERNAME", "").lstrip("@")
    if username:
        return username
    try:
        return (await request.app.state.bot.me()).username
    except TelegramAPIError as e:
        logger.warning("Cannot get bot username: %s", e)
        return None


NO_BOT_NAME = ("Не удалось связаться с Telegram, чтобы узнать имя бота. "
               "Проверьте интернет на сервере или укажите BOT_USERNAME в .env.")


def upload_path(token: str) -> Path:
    return UPLOAD_DIR / f"web_{token}.xlsx"


# ---------- страницы ----------

def register_routes(app: FastAPI) -> None:  # noqa: C901 — все маршруты в одном месте, так проще читать

    @app.exception_handler(LoginRequired)
    async def to_login(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?{urlencode({'next': request.url.path})}", status_code=303)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.exception("Panel error on %s", request.url.path, exc_info=exc)
        return templates.TemplateResponse(request, "error.html", {
            "code": 500, "detail": "Что-то пошло не так. Попробуйте ещё раз; если повторяется — "
                                   "пришлите администратору вывод: docker compose logs --tail 100 web"},
            status_code=500)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return templates.TemplateResponse(request, "error.html", {"code": exc.status_code, "detail": exc.detail,
                                                                  "me": None, "path": ""}, status_code=exc.status_code)

    # --- вход ---

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str = "/"):
        return render(request, "login.html", next=next, error=None)

    @app.post("/login")
    async def login(request: Request, login: str = Form(""), password: str = Form(""), next: str = Form("/"),
                    csrf: str = Form(""), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        key = request.client.host if request.client else "?"
        if throttle.blocked(key):
            return render(request, "login.html", next=next, error="Слишком много попыток. Подождите 5 минут.")
        web = await WebUserRepository(session).authenticate(login, password)
        if web is None:
            throttle.fail(key)
            logger.warning("Failed panel login for %r from %s", login, key)
            return render(request, "login.html", next=next, error="Неверный логин или пароль.")
        throttle.reset(key)
        request.session.clear()
        request.session.update(wid=web.id, ver=web.session_version)
        logger.info("Panel login: %s (%s) from %s", web.login, web.role, key)
        await audit.log(session, web, "login", details=f"с адреса {key}")
        return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request, csrf: str = Form("")):
        check_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- главная ---

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, web: WebUser = Depends(require("orders.view")),
                        session: AsyncSession = Depends(get_session)):
        tz = orders_service.TIMEZONE
        stats = StatsRepository(session)
        periods = {p: await stats.collect(period_start(p, tz)) for p in ("today", "7", "30")}
        new_orders, _ = await PanelRepository(session).orders(OrderFilters(tab="new"), tz, 0, 10)
        return render(request, "dashboard.html", web, periods=periods, new_orders=new_orders,
                      counts=await AdminRepository(session).order_counts(), top=periods["30"])

    # --- заказы ---

    def read_filters(request: Request) -> OrderFilters:
        p = request.query_params
        tab = p.get("tab", "all")
        return OrderFilters(tab=tab if tab in ORDER_FILTERS else "all", dealer_id=parse_int(p.get("dealer_id")),
                            region_id=parse_int(p.get("region_id")), date_from=parse_date(p.get("date_from")),
                            date_to=parse_date(p.get("date_to")), q=(p.get("q") or "")[:100])

    @app.get("/orders", response_class=HTMLResponse)
    async def orders(request: Request, web: WebUser = Depends(require("orders.view")),
                     session: AsyncSession = Depends(get_session)):
        f, repo, tz = read_filters(request), PanelRepository(session), orders_service.TIMEZONE
        _, total = await repo.orders(f, tz, 0, 1)
        page = paginate(total, parse_int(request.query_params.get("page")) or 1, PAGE)
        items, total = await repo.orders(f, tz, page.offset, PAGE)
        return render(request, "orders.html", web, orders=items, total=total, page=page, f=f, query=f.as_query(),
                      dealers=await repo.dealers(), regions=await repo.regions(),
                      counts=await AdminRepository(session).order_counts(), urlencode=urlencode)

    @app.get("/orders/export")
    async def orders_export(request: Request, web: WebUser = Depends(require("orders.view")),
                            session: AsyncSession = Depends(get_session)):
        items = await PanelRepository(session).orders_all(read_filters(request), orders_service.TIMEZONE)
        filename = f"jac_orders_{date.today().isoformat()}.xlsx"
        return Response(orders_excel(items, LANG), headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/orders/{order_id}", response_class=HTMLResponse)
    async def order_page(order_id: int, request: Request, web: WebUser = Depends(require("orders.view")),
                         session: AsyncSession = Depends(get_session)):
        order = await OrderRepository(session).get(order_id)
        if order is None:
            raise HTTPException(404, "Заказ не найден.")
        allowed = [s for s in STATUS_ORDER if s in TRANSITIONS.get(order.status, set())]
        return render(request, "order.html", web, order=order, allowed=allowed,
                      messages=await PanelRepository(session).messages(order.id))

    @app.post("/orders/{order_id}/status")
    async def order_status(order_id: int, request: Request, status: str = Form(...), csrf: str = Form(""),
                           web: WebUser = Depends(require("orders.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        repo = OrderRepository(session)
        order = await repo.get(order_id)
        if order is None:
            raise HTTPException(404, "Заказ не найден.")
        if not await repo.set_status(order, status):
            return back(f"/orders/{order_id}", f"Статус уже изменён: {status_text(order.status, LANG)}")
        await session.commit()
        await notify_status_change(request.app.state.bot, request.app.state.settings, session, order,
                                   actor=web.user, role="admin")
        logger.info("Panel %s set order %s → %s", web.login, order.id, order.status)
        await audit.log(session, web, "order.status", f"заказ №{order.id}", status_text(order.status, LANG).split(" —")[0])
        return back(f"/orders/{order_id}", f"Статус: {status_text(order.status, LANG).split(' —')[0]}. "
                                           "Клиент и дилер получили уведомление.")

    @app.post("/orders/{order_id}/message")
    async def order_message(order_id: int, request: Request, text: str = Form(""), csrf: str = Form(""),
                            web: WebUser = Depends(require("orders.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        text = text.strip()[:3500]
        order = await OrderRepository(session).get(order_id)
        if order is None:
            raise HTTPException(404, "Заказ не найден.")
        if not text:
            return RedirectResponse(f"/orders/{order_id}", status_code=303)
        client = order.user
        header = i18n.t(client.language, "chat_to_client_header", id=order.id, dealer=order.dealer.name)
        ok = await send(request.app.state.bot, client.telegram_id, f"{header}\n\n{text}",
                        reply_keyboard("dealer", order.id, client.language))
        session.add(OrderMessage(order_id=order.id, sender_id=web.user.id, to_side="client", text=text))
        await session.commit()
        await audit.log(session, web, "order.message", f"заказ №{order.id}", text[:300])
        return back(f"/orders/{order_id}", "Сообщение отправлено клиенту в Telegram." if ok
                    else "Не удалось доставить: клиент заблокировал бота.")

    # --- сотрудники и роли ---

    @app.get("/staff", response_class=HTMLResponse)
    async def staff(request: Request, web: WebUser = Depends(require("staff")),
                    session: AsyncSession = Depends(get_session)):
        people = await WebUserRepository(session).all()
        admin_ids = request.app.state.settings.admin_ids
        return render(request, "staff.html", web, people=people, admin_ids=admin_ids,
                      invite_link=request.query_params.get("link"), invite_role=request.query_params.get("role"))

    @app.post("/staff/invite")
    async def staff_invite(request: Request, role: str = Form(...), csrf: str = Form(""),
                           web: WebUser = Depends(require("staff")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        if role not in ROLES:
            raise HTTPException(400, "Неизвестная роль.")
        username = await bot_username(request)
        if not username:
            return back("/staff", NO_BOT_NAME)
        token = await WebUserRepository(session).create_invite(role, web.user)
        link = f"https://t.me/{username}?start=staff_{token}"
        logger.info("Panel %s created invite for role %s", web.login, role)
        await audit.log(session, web, "staff.invite", details=f"роль: {ROLES[role]}")
        return RedirectResponse(f"/staff?{urlencode({'link': link, 'role': role})}", status_code=303)

    async def _person(session: AsyncSession, person_id: int, me: WebUser, admin_ids: set[int]) -> WebUser:
        person = await WebUserRepository(session).get(person_id)
        if person is None:
            raise HTTPException(404, "Сотрудник не найден.")
        if person.id == me.id:
            raise HTTPException(400, "Нельзя менять собственную роль или доступ.")
        if person.user.telegram_id in admin_ids:
            raise HTTPException(400, "Этот человек — администратор из ADMIN_IDS (.env). Менять его можно только там.")
        return person

    @app.post("/staff/{person_id}/role")
    async def staff_role(person_id: int, request: Request, role: str = Form(...), csrf: str = Form(""),
                         web: WebUser = Depends(require("staff")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        person = await _person(session, person_id, web, request.app.state.settings.admin_ids)
        if role not in ROLES:
            raise HTTPException(400, "Неизвестная роль.")
        await WebUserRepository(session).set_role(person, role)
        logger.info("Panel %s set role of %s → %s", web.login, person.login, role)
        await audit.log(session, web, "staff.role", person.login, ROLES[role])
        return back("/staff", f"{person_name(person.user)}: роль «{ROLES[role]}».")

    @app.post("/staff/{person_id}/active")
    async def staff_active(person_id: int, request: Request, active: str = Form(...), csrf: str = Form(""),
                           web: WebUser = Depends(require("staff")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        person = await _person(session, person_id, web, request.app.state.settings.admin_ids)
        enable = active == "1"
        await WebUserRepository(session).set_active(person, enable)
        if not enable:
            await send(request.app.state.bot, person.user.telegram_id,
                       i18n.t(person.user.language, "panel_disabled_notice"))
        logger.info("Panel %s %s %s", web.login, "enabled" if enable else "disabled", person.login)
        await audit.log(session, web, "staff.active", person.login, "включён" if enable else "отключён")
        return back("/staff", f"{person_name(person.user)}: доступ {'включён' if enable else 'отключён'}.")

    @app.post("/staff/{person_id}/password")
    async def staff_password(person_id: int, request: Request, csrf: str = Form(""),
                             web: WebUser = Depends(require("staff")), session: AsyncSession = Depends(get_session)):
        """Новый пароль уходит сотруднику в Telegram — в панели он не показывается."""
        check_csrf(request, csrf)
        person = await _person(session, person_id, web, request.app.state.settings.admin_ids)
        login, password = await WebUserRepository(session).issue_password(person.user)
        settings: Settings = request.app.state.settings
        lang = person.user.language
        ok = await send(request.app.state.bot, person.user.telegram_id, i18n.t(
            lang, "web_password", url=settings.web_url or i18n.t(lang, "web_url_missing"),
            login=login, password=password, role=ROLES[person.role]), parse_mode="HTML")
        await audit.log(session, web, "staff.password", person.login)
        return back("/staff", "Новый пароль отправлен сотруднику в Telegram." if ok
                    else "Не удалось отправить: сотрудник заблокировал бота.")

    # --- дилеры ---

    @app.get("/dealers", response_class=HTMLResponse)
    async def dealers(request: Request, web: WebUser = Depends(require("dealers.view")),
                      session: AsyncSession = Depends(get_session)):
        p, repo = request.query_params, PanelRepository(session)
        q, region_id, state = (p.get("q") or "")[:100], parse_int(p.get("region_id")), p.get("state", "")
        return render(request, "dealers.html", web, lines=await repo.dealer_lines(q, region_id, state),
                      regions=await repo.regions(), q=q, region_id=region_id, state=state)

    async def _dealer(session: AsyncSession, dealer_id: int) -> Dealer:
        dealer = await session.get(Dealer, dealer_id)
        if dealer is None:
            raise HTTPException(404, "Дилер не найден.")
        return dealer

    @app.get("/dealers/{dealer_id}", response_class=HTMLResponse)
    async def dealer_page(dealer_id: int, request: Request, web: WebUser = Depends(require("dealers.view")),
                          session: AsyncSession = Depends(get_session)):
        dealer = await _dealer(session, dealer_id)
        repo = PanelRepository(session)
        line = next((x for x in await repo.dealer_lines() if x.dealer.id == dealer.id), None)
        recent, _ = await PanelRepository(session).orders(OrderFilters(dealer_id=dealer.id), orders_service.TIMEZONE, 0, 10)
        return render(request, "dealer.html", web, dealer=dealer, line=line, regions=await repo.regions(),
                      staff=await StaffRepository(session).staff_of(dealer.id), recent=recent,
                      counts=await AdminRepository(session).order_counts(dealer_id=dealer.id),
                      invite_link=request.query_params.get("link"))

    @app.post("/dealers/{dealer_id}")
    async def dealer_save(dealer_id: int, request: Request, phone: str = Form(""), address: str = Form(""),
                          region_id: int = Form(...), csrf: str = Form(""),
                          web: WebUser = Depends(require("dealers.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        dealer = await _dealer(session, dealer_id)
        if await session.get(Region, region_id) is None:
            raise HTTPException(400, "Неизвестный регион.")
        dealer.phone, dealer.address = phone.strip()[:32] or None, address.strip()[:512] or None
        dealer.region_id = region_id
        await session.commit()
        logger.info("Panel %s edited dealer %s", web.login, dealer.id)
        await audit.log(session, web, "dealer.edit", dealer.name, f"тел. {dealer.phone or '—'}; адрес: {dealer.address or '—'}; регион id {dealer.region_id}")
        return back(f"/dealers/{dealer.id}", "Сохранено. Клиенты увидят новые данные сразу.")

    @app.post("/dealers/{dealer_id}/enabled")
    async def dealer_enabled(dealer_id: int, request: Request, enabled: str = Form(...), csrf: str = Form(""),
                             web: WebUser = Depends(require("dealers.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        dealer = await _dealer(session, dealer_id)
        dealer.enabled = enabled == "1"
        await session.commit()
        logger.info("Panel %s set dealer %s enabled=%s", web.login, dealer.id, dealer.enabled)
        await audit.log(session, web, "dealer.enabled", dealer.name, "включён" if dealer.enabled else "выключен")
        return back(f"/dealers/{dealer.id}", "Дилер включён: его детали снова видны клиентам." if dealer.enabled
                    else "Дилер выключен: его детали скрыты из бота. Открытые заказы остаются.")

    @app.post("/dealers/{dealer_id}/invite")
    async def dealer_invite(dealer_id: int, request: Request, csrf: str = Form(""),
                            web: WebUser = Depends(require("dealers.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        dealer = await _dealer(session, dealer_id)
        username = await bot_username(request)
        if not username:
            return back(f"/dealers/{dealer.id}", NO_BOT_NAME)
        token = await StaffRepository(session).create_invite(dealer.id)
        logger.info("Panel %s created dealer invite for %s", web.login, dealer.id)
        await audit.log(session, web, "dealer.invite", dealer.name)
        link = f"https://t.me/{username}?start=dealer_{token}"
        return RedirectResponse(f"/dealers/{dealer.id}?{urlencode({'link': link})}", status_code=303)

    @app.post("/dealers/{dealer_id}/staff/{staff_id}/remove")
    async def dealer_staff_remove(dealer_id: int, staff_id: int, request: Request, csrf: str = Form(""),
                                  web: WebUser = Depends(require("dealers.edit")),
                                  session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        staff = await session.get(DealerStaff, staff_id)
        if staff is None or staff.dealer_id != dealer_id:
            raise HTTPException(404, "Сотрудник дилера не найден.")
        name = person_name(staff.user)
        await StaffRepository(session).remove(staff_id)
        logger.info("Panel %s removed dealer staff %s from %s", web.login, staff_id, dealer_id)
        await audit.log(session, web, "dealer.staff_remove", f"дилер id {dealer_id}", name)
        return back(f"/dealers/{dealer_id}", f"{name} больше не получает заказы этого дилера.")

    # --- клиенты ---

    @app.get("/clients", response_class=HTMLResponse)
    async def clients(request: Request, web: WebUser = Depends(require("clients.view")),
                      session: AsyncSession = Depends(get_session)):
        p, repo = request.query_params, PanelRepository(session)
        q, who = (p.get("q") or "")[:100], p.get("who", "")
        _, total = await repo.client_lines(q, who, 0, 1)
        page = paginate(total, parse_int(p.get("page")) or 1, PAGE)
        lines, total = await repo.client_lines(q, who, page.offset, PAGE)
        query = {k: v for k, v in {"q": q, "who": who}.items() if v}
        return render(request, "clients.html", web, lines=lines, total=total, page=page, q=q, who=who,
                      query=query, urlencode=urlencode)

    async def _client(session: AsyncSession, user_id: int) -> User:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(404, "Клиент не найден.")
        return user

    @app.get("/clients/{user_id}", response_class=HTMLResponse)
    async def client_page(user_id: int, request: Request, web: WebUser = Depends(require("clients.view")),
                          session: AsyncSession = Depends(get_session)):
        client = await _client(session, user_id)
        lines, _ = await PanelRepository(session).client_lines(who="all", user_id=client.id)
        orders_, total = await AdminRepository(session).orders_page("all", 0, 100, user_id=client.id)
        staff_dealer_id = await StaffRepository(session).dealer_id_for(client)
        staff_dealer = await session.get(Dealer, staff_dealer_id) if staff_dealer_id else None
        line = lines[0] if lines else None
        return render(request, "client.html", web, client=client, line=line, orders=orders_, total=total,
                      staff_dealer=staff_dealer, is_admin=client.telegram_id in request.app.state.settings.admin_ids)

    @app.post("/clients/{user_id}/message")
    async def client_message(user_id: int, request: Request, text: str = Form(""), csrf: str = Form(""),
                             web: WebUser = Depends(require("clients.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        client = await _client(session, user_id)
        text = text.strip()[:3500]
        if not text:
            return RedirectResponse(f"/clients/{client.id}", status_code=303)
        header = i18n.t(client.language, "direct_message_header")
        ok = await send(request.app.state.bot, client.telegram_id, f"{header}\n\n{text}")
        logger.info("Panel %s messaged user %s (ok=%s)", web.login, client.id, ok)
        await audit.log(session, web, "client.message", person_name(client), text[:300])
        return back(f"/clients/{client.id}", "Сообщение отправлено в Telegram." if ok
                    else "Не удалось доставить: клиент заблокировал бота или ни разу его не запускал.")

    @app.post("/clients/{user_id}/blocked")
    async def client_blocked(user_id: int, request: Request, blocked: str = Form(...), csrf: str = Form(""),
                             web: WebUser = Depends(require("clients.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        client = await _client(session, user_id)
        if client.telegram_id in request.app.state.settings.admin_ids:
            raise HTTPException(400, "Это администратор из ADMIN_IDS (.env) — его заблокировать нельзя.")
        if client.id == web.user.id:
            raise HTTPException(400, "Нельзя заблокировать самого себя.")
        await PanelRepository(session).set_blocked(client, blocked == "1")
        logger.info("Panel %s set user %s blocked=%s", web.login, client.id, client.blocked)
        await audit.log(session, web, "client.blocked", person_name(client), "заблокирован" if client.blocked else "разблокирован")
        return back(f"/clients/{client.id}", "Клиент заблокирован: бот больше не будет ему отвечать." if client.blocked
                    else "Клиент разблокирован.")

    # --- каталог ---

    @app.get("/catalog", response_class=HTMLResponse)
    async def catalog(request: Request, web: WebUser = Depends(require("catalog.view")),
                      session: AsyncSession = Depends(get_session)):
        p, repo = request.query_params, PanelRepository(session)
        q, show = (p.get("q") or "")[:100], p.get("show", "")
        model_id, node_id = parse_int(p.get("model_id")), parse_int(p.get("node_id"))
        _, total = await repo.part_lines(q, model_id, node_id, show, 0, 1)
        page = paginate(total, parse_int(p.get("page")) or 1, PAGE)
        lines, total = await repo.part_lines(q, model_id, node_id, show, page.offset, PAGE)
        query = {k: v for k, v in {"q": q, "show": show, "model_id": model_id or "", "node_id": node_id or ""}.items() if v}
        return render(request, "catalog.html", web, lines=lines, total=total, page=page, q=q, show=show,
                      model_id=model_id, node_id=node_id, models=await repo.models(), nodes=await repo.nodes(),
                      summary=await AdminRepository(session).catalog_summary(),
                      untranslated=await repo.untranslated_count(), query=query, urlencode=urlencode)

    async def _part(session: AsyncSession, part_id: int) -> Part:
        part = await session.get(Part, part_id)
        if part is None:
            raise HTTPException(404, "Деталь не найдена.")
        return part

    @app.get("/catalog/{part_id}", response_class=HTMLResponse)
    async def part_page(part_id: int, request: Request, web: WebUser = Depends(require("catalog.view")),
                        session: AsyncSession = Depends(get_session)):
        part, repo = await _part(session, part_id), PanelRepository(session)
        return render(request, "part.html", web, part=part, offers=await repo.part_offers(part.id),
                      same=await repo.same_name_parts(part), tr=await repo.translation_for(part),
                      back_url=request.query_params.get("back") or "/catalog")

    @app.post("/catalog/{part_id}/translation")
    async def part_translation(part_id: int, request: Request, name_ru: str = Form(""), name_uz: str = Form(""),
                               csrf: str = Form(""), next_untranslated: str = Form(""),
                               web: WebUser = Depends(require("catalog.edit")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        part, repo = await _part(session, part_id), PanelRepository(session)
        changed = await repo.save_translation(part, name_ru, name_uz, web.user)
        logger.info("Panel %s translated part %s (%d parts)", web.login, part.id, changed)
        await audit.log(session, web, "part.translation", part.part_number, f"RU: {name_ru or '—'}; UZ: {name_uz or '—'} ({changed} дет.)")
        flash = f"Перевод сохранён ({changed} дет.). В боте — сразу, и сохранится при следующих загрузках Excel."
        if next_untranslated:
            lines, _ = await repo.part_lines(show="untranslated", limit=1)
            if lines:
                return back(f"/catalog/{lines[0].part.id}?back=/catalog?show=untranslated", flash)
            return back("/catalog?show=untranslated", flash + " Непереведённых больше нет 🎉")
        return back(f"/catalog/{part.id}", flash)

    # --- загрузка Excel ---

    @app.get("/upload", response_class=HTMLResponse)
    async def upload_page(request: Request, web: WebUser = Depends(require("upload"))):
        return render(request, "upload.html", web, step="choose", max_mb=MAX_FILE_MB)

    @app.post("/upload", response_class=HTMLResponse)
    async def upload_check(request: Request, file: UploadFile = File(...), csrf: str = Form(""),
                           web: WebUser = Depends(require("upload")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        _drop_upload(request)
        if not (file.filename or "").lower().endswith(".xlsx"):
            return render(request, "upload.html", web, step="choose", max_mb=MAX_FILE_MB,
                          error="Нужен файл Excel с расширением .xlsx")
        data = await file.read(MAX_FILE_MB * 1024 * 1024 + 1)
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            return render(request, "upload.html", web, step="choose", max_mb=MAX_FILE_MB,
                          error=f"Файл больше {MAX_FILE_MB} МБ.")
        token = secrets.token_hex(8)
        path = upload_path(token)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        rows, errors, warnings, fmt = await import_flow.validate_path(session, path)
        if errors:
            path.unlink(missing_ok=True)
            return render(request, "upload.html", web, step="errors", max_mb=MAX_FILE_MB, filename=file.filename,
                          text=import_flow.errors_text(errors, LANG))
        stats = await import_flow.dry_run(request.app.state.session_factory, rows, fmt)
        await session.refresh(web)  # если пробный прогон шёл в этой же сессии (тесты) — данные после отката
        request.session["upload"] = token
        return render(request, "upload.html", web, step="preview", max_mb=MAX_FILE_MB, filename=file.filename,
                      token=token, text=import_flow.preview_text(stats, warnings, fmt, LANG, question=False))

    def _drop_upload(request: Request) -> None:
        token = request.session.pop("upload", None)
        if token:
            upload_path(token).unlink(missing_ok=True)

    @app.post("/upload/apply", response_class=HTMLResponse)
    async def upload_apply(request: Request, token: str = Form(""), action: str = Form("apply"), csrf: str = Form(""),
                           web: WebUser = Depends(require("upload")), session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        if not token or token != request.session.get("upload") or not upload_path(token).exists():
            return back("/upload", "Файл не найден (устарел или уже применён) — загрузите его заново.")
        path = upload_path(token)
        if action != "apply":
            _drop_upload(request)
            return back("/upload", "Загрузка отменена. База не изменена.")
        try:
            rows, errors, _, fmt = await import_flow.validate_path(session, path)  # ещё раз: база могла измениться
            if errors:
                return render(request, "upload.html", web, step="errors", max_mb=MAX_FILE_MB,
                              text=import_flow.errors_text(errors, LANG))
            async with request.app.state.session_factory() as db:
                try:
                    stats = await import_flow.run_import(db, rows, fmt)
                    await db.commit()  # всё или ничего
                except Exception:
                    await db.rollback()
                    logger.exception("Panel import failed, rolled back")
                    return render(request, "upload.html", web, step="errors", max_mb=MAX_FILE_MB,
                                  text=i18n.t(LANG, "import_db_error"))
        finally:
            _drop_upload(request)
        logger.info("Panel import by %s: %s", web.login, stats)
        await audit.log(session, web, "upload.apply", import_flow.stats_text("applied", stats, fmt, LANG).split("\n")[0], str(vars(stats)))
        return render(request, "upload.html", web, step="done", max_mb=MAX_FILE_MB,
                      text=import_flow.stats_text("applied", stats, fmt, LANG))

    # --- статистика ---

    STAT_PERIODS = [("today", "Сегодня"), ("7", "7 дней"), ("30", "30 дней"), ("90", "90 дней"), ("all", "Всё время")]

    @app.get("/stats", response_class=HTMLResponse)
    async def stats_page(request: Request, web: WebUser = Depends(require("stats")),
                         session: AsyncSession = Depends(get_session)):
        p, tz = request.query_params, orders_service.TIMEZONE
        date_from, date_to = parse_date(p.get("date_from")), parse_date(p.get("date_to"))
        period = p.get("period", "30")
        if date_from or date_to:
            period = "custom"
            since = datetime.combine(date_from, dtime.min, tzinfo=tz).astimezone(timezone.utc) if date_from else None
            until = (datetime.combine(date_to + timedelta(days=1), dtime.min, tzinfo=tz).astimezone(timezone.utc)
                     if date_to else None)
        else:
            period = period if period in dict(STAT_PERIODS) else "30"
            since = (period_start("30", tz) - timedelta(days=60) if period == "90" else period_start(period, tz))
            until = None
        repo = StatsRepository(session)
        st = await repo.collect(since, until)
        days = await repo.daily(since, until, tz)
        many = len(days) > 45
        orders_chart = bar_chart([(d.day.strftime("%d.%m"), d.orders, f"{d.day:%d.%m.%Y}: {d.orders} заказ(ов)")
                                  for d in days])
        revenue_chart = bar_chart([(d.day.strftime("%d.%m"), d.revenue, f"{d.day:%d.%m.%Y}: {money(d.revenue, LANG)}")
                                   for d in days])
        # период для ссылки «заказы за период» и выгрузки в Excel
        first = since.astimezone(tz).date().isoformat() if since else ""
        last = (until - timedelta(seconds=1)).astimezone(tz).date().isoformat() if until else ""
        export_q = urlencode({k: v for k, v in {"date_from": first, "date_to": last}.items() if v})
        return render(request, "stats.html", web, st=st, periods=STAT_PERIODS, period=period, date_from=date_from,
                      date_to=date_to, orders_chart=orders_chart, revenue_chart=revenue_chart, many=many,
                      export_q=export_q, max_region=max([t for _, _, t in st.by_region], default=0),
                      max_dealer=max([t for _, _, t in st.by_dealer], default=0))

    # --- рассылка ---

    def read_audience(region_id: str | None, language: str | None, buyers: str | None):
        return broadcast_service.Audience(region_id=parse_int(region_id),
                                          language=language if language in ("ru", "uz", "en") else "",
                                          buyers_only=buyers == "1")

    @app.get("/broadcast", response_class=HTMLResponse)
    async def broadcast_page(request: Request, web: WebUser = Depends(require("broadcast")),
                             session: AsyncSession = Depends(get_session)):
        p = request.query_params
        aud = read_audience(p.get("region_id"), p.get("language"), p.get("buyers"))
        history = list((await session.scalars(select(Broadcast).order_by(Broadcast.id.desc()).limit(20))).unique())
        return render(request, "broadcast.html", web, aud=aud, count=await aud.count(session),
                      regions=await PanelRepository(session).regions(), history=history,
                      text=p.get("text", ""), sending=any(b.status == "sending" for b in history))

    @app.post("/broadcast/test")
    async def broadcast_test(request: Request, text: str = Form(""), csrf: str = Form(""),
                             web: WebUser = Depends(require("broadcast"))):
        check_csrf(request, csrf)
        text = text.strip()[:4000]
        if not text:
            return back("/broadcast", "Напишите текст сообщения.")
        ok = await send(request.app.state.bot, web.user.telegram_id, text)
        return back(f"/broadcast?{urlencode({'text': text})}", "Пробное сообщение отправлено вам в Telegram."
                    if ok else "Не удалось отправить вам сообщение — откройте бота и нажмите /start.")

    @app.post("/broadcast")
    async def broadcast_send(request: Request, text: str = Form(""), region_id: str = Form(""),
                             language: str = Form(""), buyers: str = Form(""), confirm: str = Form(""),
                             csrf: str = Form(""), web: WebUser = Depends(require("broadcast")),
                             session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        text = text.strip()[:4000]
        aud = read_audience(region_id, language, buyers)
        query = urlencode({"text": text, "region_id": region_id, "language": language, "buyers": buyers})
        if not text:
            return back(f"/broadcast?{query}", "Напишите текст сообщения.")
        if confirm != "1":
            return back(f"/broadcast?{query}", "Поставьте галочку «Я проверил текст», чтобы отправить.")
        if await session.scalar(select(func.count(Broadcast.id)).where(Broadcast.status == "sending")):
            return back(f"/broadcast?{query}", "Предыдущая рассылка ещё идёт — дождитесь её окончания.")
        chat_ids = await aud.telegram_ids(session)
        if not chat_ids:
            return back(f"/broadcast?{query}", "Под выбранные условия не подходит ни один клиент.")
        described = await aud.describe(session)
        b = Broadcast(text=text, audience=described, created_by=web.user.id, total=len(chat_ids))
        session.add(b)
        await session.commit()
        await audit.log(session, web, "broadcast", f"{described}: {len(chat_ids)} чел.", text[:300])
        task = asyncio.create_task(broadcast_service.run(
            b.id, chat_ids, text, request.app.state.bot, request.app.state.session_factory))
        request.app.state.tasks.add(task)
        task.add_done_callback(request.app.state.tasks.discard)
        return back("/broadcast", f"Рассылка запущена: {len(chat_ids)} получателей. "
                                  f"Это займёт около {max(1, round(len(chat_ids) * broadcast_service.DELAY / 60 + 0.5))} мин.")

    # --- настройки ---

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request, web: WebUser = Depends(require("settings")),
                            session: AsyncSession = Depends(get_session)):
        values = await bot_settings.load(session)
        preview, _ = bot_settings.contact_view(values, LANG)
        regions = list(await session.scalars(select(Region).order_by(Region.sort_order, Region.id)))
        users = dict((await session.execute(
            select(User.region_id, func.count(User.id)).where(User.region_id.is_not(None))
            .group_by(User.region_id))).all())
        dealers = dict((await session.execute(
            select(Dealer.region_id, func.count(Dealer.id)).group_by(Dealer.region_id))).all())
        return render(request, "settings.html", web, values=values, fields=bot_settings.CONTACT_FIELDS,
                      preview=preview, regions=regions, users=users, dealers=dealers)

    @app.post("/settings/contacts")
    async def settings_contacts(request: Request, web: WebUser = Depends(require("settings")),
                                session: AsyncSession = Depends(get_session)):
        form = await request.form()
        check_csrf(request, str(form.get("csrf", "")))
        values = {k: str(form.get(k, "")).strip()[:300] for k in bot_settings.CONTACT_FIELDS}
        if values["contact_telegram"] and not bot_settings.telegram_username(values["contact_telegram"]):
            return back("/settings", "Telegram указан неверно: нужен @username (буквы, цифры, _; от 4 символов).")
        await bot_settings.save(session, values)
        await audit.log(session, web, "settings.contacts", details="; ".join(f"{k}={v}" for k, v in values.items() if v))
        return back("/settings", "Сохранено. Кнопка «📞 Менеджер» в боте уже показывает новые контакты.")

    @app.post("/settings/regions/{region_id}")
    async def settings_region(region_id: int, request: Request, name_ru: str = Form(""), name_uz: str = Form(""),
                              name_en: str = Form(""), sort_order: str = Form("0"), active: str = Form(""),
                              csrf: str = Form(""), web: WebUser = Depends(require("settings")),
                              session: AsyncSession = Depends(get_session)):
        check_csrf(request, csrf)
        region = await session.get(Region, region_id)
        if region is None:
            raise HTTPException(404, "Регион не найден.")
        if not name_ru.strip():
            return back("/settings#regions", "Название на русском обязательно.")
        region.name_ru, region.name_uz, region.name_en = name_ru.strip()[:128], name_uz.strip()[:128] or None, \
            name_en.strip()[:128] or None
        region.sort_order = int(sort_order) if sort_order.lstrip("-").isdigit() else region.sort_order
        region.active = active == "1"
        await session.commit()
        await audit.log(session, web, "region.edit", region.name_ru,
                        f"UZ: {region.name_uz or '—'}; EN: {region.name_en or '—'}; порядок {region.sort_order}; "
                        f"{'показывается' if region.active else 'скрыт'}")
        return back("/settings#regions", f"Регион «{region.name_ru}» сохранён.")

    # --- журнал действий ---

    @app.get("/audit", response_class=HTMLResponse)
    async def audit_page(request: Request, web: WebUser = Depends(require("audit")),
                         session: AsyncSession = Depends(get_session)):
        p = request.query_params
        login_f, action_f = (p.get("login") or "")[:64], p.get("action", "")
        query = select(AuditLog)
        if login_f:
            query = query.where(AuditLog.login == login_f)
        if action_f in audit.ACTIONS:
            query = query.where(AuditLog.action == action_f)
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        page = paginate(total, parse_int(p.get("page")) or 1, 100)
        rows = list(await session.scalars(query.order_by(AuditLog.id.desc()).offset(page.offset).limit(100)))
        logins = list(await session.scalars(select(AuditLog.login).distinct().order_by(AuditLog.login)))
        q = {k: v for k, v in {"login": login_f, "action": action_f}.items() if v}
        return render(request, "audit.html", web, rows=rows, total=total, page=page, logins=logins,
                      login_f=login_f, action_f=action_f, actions=audit.ACTIONS, query=q, urlencode=urlencode)

    @app.get("/health")
    async def health():
        return {"ok": True}
