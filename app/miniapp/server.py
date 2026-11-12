"""Витрина в Telegram (Mini App) — отдельный маленький сервис.

Это единственное, что видно из интернета (через Tailscale Funnel, см. README «Витрина в Telegram»).
Веб-панели здесь нет. Каждый запрос к /api подписан самим Telegram (initData): подделать его
без токена бота нельзя, поэтому витрина знает, какой клиент её открыл, без логина и пароля.

Запуск (docker-compose, сервис miniapp):
    uvicorn --factory app.miniapp.server:create_app --port 8095
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, load_settings
from app.database.database import create_engine, create_session_factory
from app.database.models import Dealer, Order, Part, User
from app.database.repositories.cart import CartRepository, item_available
from app.database.repositories.catalog import CatalogRepository
from app.database.repositories.orders import CheckoutError, OrderRepository
from app.database.repositories.regions import RegionRepository
from app.database.repositories.users import UserRepository
from app.database.repositories.staff import StaffRepository
from app.database.repositories.stocks import StockRepository
from app.services import cars
from app.services import orders as orders_service
from app.services.catalog import map_url, money, region_days
from app.services.import_mapping import ALL_MODELS, CATEGORIES
from app.services.localization import i18n, localized_name
from app.services.orders import fmt_date, order_status, progress_steps, stock_problems_text
from app.services.part_photos import NAME_RE, URL_PREFIX, image_bytes
from app.services.pictures import picture_key
from app.services.vin import MAX_UPLOAD, check_digit_ok, is_valid, normalize, read_vin

logger = logging.getLogger(__name__)
HERE = Path(__file__).parent
STATIC = HERE / "static"
MAX_AGE = 24 * 3600  # initData старше суток не принимаем — пусть клиент откроет витрину заново
PAGE = 30
ICONS = {ru: key for key, (ru, _, _) in zip(("service", "body", "brakes", "electric", "tools"), CATEGORIES.values())}


# ---------- запуск ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    orders_service.set_timezone(settings.timezone)
    engine = None
    if app.state.session_factory is None:  # в тестах подставляется своя база
        engine = create_engine(settings.database_url)
        app.state.session_factory = create_session_factory(engine)
    if app.state.bot is None:
        app.state.bot = Bot(token=settings.bot_token)  # только чтобы отправлять уведомления о заказах
    yield
    await app.state.bot.session.close()
    if engine is not None:
        await engine.dispose()


def asset_version() -> str:
    """Хэш app.js, app.css и pics.js — чтобы после обновления Telegram не показывал старую витрину из кэша."""
    digest = hashlib.sha256()
    for name in ("app.js", "app.css", "pics.js"):
        digest.update((STATIC / name).read_bytes())
    return digest.hexdigest()[:10]


SECURITY_HEADERS = {
    # скрипт Telegram — единственный внешний; шрифты и всё остальное — свои
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' https: data: blob:; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def create_app(settings: Settings | None = None, session_factory=None, bot: Bot | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app = FastAPI(title="JAC Parts", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.session_factory, app.state.bot = settings, session_factory, bot
    app.state.limiter = RateLimiter()
    app.state.scan_limiter = RateLimiter(limit=20)  # распознавание VIN тяжёлое — не чаще 20 фото в минуту
    app.state.scan_slots = asyncio.Semaphore(2)  # и не больше двух одновременно на весь сервер
    index = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{v}}", asset_version())

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def page() -> HTMLResponse:
        return HTMLResponse(index, headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    register_api(app)
    return app


# ---------- кто открыл витрину ----------

class RateLimiter:
    """Не больше 240 запросов в минуту от одного клиента — защита от зацикленного или чужого скрипта."""

    def __init__(self, limit: int = 240, window: float = 60):
        self.limit, self.window = limit, window
        self.hits: dict[int, list[float]] = {}

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        hits = [t for t in self.hits.get(key, []) if now - t < self.window]
        hits.append(now)
        self.hits[key] = hits
        if len(self.hits) > 10_000:  # не копим память по давно ушедшим клиентам
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
        return len(hits) <= self.limit


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


class Client:
    def __init__(self, user: User, staff_dealer_id: int | None):
        self.user, self.staff_dealer_id = user, staff_dealer_id

    @property
    def lang(self) -> str | None:
        return self.user.language

    @property
    def full(self) -> bool:
        """Все модели — только у сотрудников дилеров (как в боте), остальным — автомобиль из профиля."""
        return self.staff_dealer_id is not None

    def models(self) -> set[str] | None:
        return None if self.full else {cars.catalog_model(self.user), ALL_MODELS[0]}


def check_init_data(raw: str, token: str, now: datetime | None = None) -> int:
    """initData из Telegram → telegram_id клиента. Подпись проверяется токеном бота. Ошибка → 401."""
    try:
        data = safe_parse_webapp_init_data(token, raw)
    except ValueError:
        raise HTTPException(401, "bad_signature")
    if data.user is None:
        raise HTTPException(401, "no_user")
    auth = data.auth_date if data.auth_date.tzinfo else data.auth_date.replace(tzinfo=timezone.utc)
    if ((now or datetime.now(timezone.utc)) - auth).total_seconds() > MAX_AGE:
        raise HTTPException(401, "expired")
    return data.user.id


async def client(request: Request, session: AsyncSession = Depends(get_session)) -> Client:
    settings: Settings = request.app.state.settings
    telegram_id = check_init_data(request.headers.get("X-Telegram-Init-Data", ""), settings.bot_token)
    if not request.app.state.limiter.allow(telegram_id):
        raise HTTPException(429, "too_many")
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is not None and user.blocked and telegram_id not in settings.admin_ids:
        raise HTTPException(403, "blocked")
    if user is None or not (user.language and user.region_id and user.phone):
        raise HTTPException(403, "register")  # регистрация (язык, регион, телефон) — только в боте
    return Client(user, await StaffRepository(session).dealer_id_for(user))


# ---------- что отдаём ----------

def dealer_json(dealer: Dealer) -> dict:
    return {"id": dealer.id, "name": dealer.name, "address": dealer.address, "phone": dealer.phone,
            "map": map_url(dealer)}


def part_brief(part: Part, info: dict, c: Client) -> dict:
    """Строка в списке: цена у дилеров региона (лучшая) или со склада JAC (под заказ)."""
    lang = c.lang
    price = info["local"] if info["local"] is not None else info["warehouse"]
    status = "stock" if info["local"] is not None else "preorder" if info["warehouse"] is not None else "none"
    return {"id": part.id, "name": localized_name(part, lang), "number": part.part_number, "photo": part.photo,
            "icon": ICONS.get(part.node.name_ru, "other"), "pic": picture_key(part.name_en, part.name_ru),
            "price": money(price, lang) if price is not None else None, "status": status,
            "dealers": info["dealers"], "days": region_days(c.user.region, lang) if status == "preorder" else None}


async def briefs(session: AsyncSession, parts: list[Part], c: Client) -> list[dict]:
    info = await StockRepository(session).price_info([p.id for p in parts], c.user.region_id)
    return [part_brief(p, info[p.id], c) for p in parts]


def ui_texts(lang: str | None) -> dict[str, str]:
    """Все подписи витрины (ключи ma_* в app/locales/*.json) — переводы в одном месте с ботом."""
    base = i18n.texts[i18n.default]
    mine = i18n.texts.get(lang or i18n.default, {})
    return {k[3:]: mine.get(k, v) for k, v in base.items() if k.startswith("ma_")}


async def cart_json(session: AsyncSession, c: Client) -> dict:
    lang = c.lang
    items = await CartRepository(session).items(c.user)
    lines, total, groups = [], 0, set()
    for item in items:
        stock, part = item.stock, item.stock.part
        ok = item_available(item)
        qty = min(item.quantity, stock.quantity) if ok else 0
        total += stock.price * qty
        warehouse = stock.dealer.is_warehouse
        dealer = item.pickup_dealer if warehouse else stock.dealer
        if ok:
            groups.add((dealer.id, warehouse))
        lines.append({
            "id": item.id, "part_id": part.id, "name": localized_name(part, lang), "number": part.part_number,
            "photo": part.photo, "icon": ICONS.get(part.node.name_ru, "other"),
            "pic": picture_key(part.name_en, part.name_ru), "qty": item.quantity, "max": stock.quantity, "available": ok,
            "price": money(stock.price, lang), "subtotal": money(stock.price * qty, lang),
            "preorder": warehouse, "dealer": dealer.name if dealer else None,
            "days": region_days(dealer.region if dealer else None, lang) if warehouse else None,
        })
    return {"items": lines, "count": sum(i.quantity for i in items), "total": money(total, lang),
            "orders": len(groups), "phone": c.user.phone}


def order_json(order: Order, lang: str | None) -> dict:
    return {
        "id": order.id, "date": fmt_date(order.created_at), "total": money(order.total_amount, lang),
        "status": order.status, "status_text": order_status(order, lang), "preorder": order.preorder,
        "dealer": dealer_json(order.dealer),
        "items": [{"name": localized_name(i, lang), "number": i.part_number, "qty": i.quantity} for i in order.items],
        "steps": [{"label": label, "state": state} for label, state in progress_steps(order, lang)],
        "days": region_days(order.dealer.region, lang) if order.preorder else None,
    }


COLOR_HEX = {"white": "#f4f4f4", "black": "#1b1c1e", "silver": "#c3c6ca", "gray": "#8b8e93", "metallic_gray": "#6c7177",
             "star_gray": "#b6babf", "red": "#b3162b", "blue": "#2b5aa8"}
LANGUAGES = ("ru", "uz", "en")

# Фото моделей JAC: static/cars/<ключ>.webp (большое) и <ключ>-s.webp (маленькое, для списков).
# Нет файла — витрина рисует схематичную машину. Добавить фото T9: положите t9.webp и t9-s.webp (16:9).
CAR_PHOTOS = {"JAC M3": "m3", "JAC M4": "m4", "JAC Sunray": "sunray", "JAC T8": "t8", "JAC T9": "t9",
              "JAC JS8": "js8", "JAC RF8": "rf8"}
MOD_PHOTOS = {("JAC M3", "van"): "m3-van"}  # у комплектации свой вид — своё фото


def car_photo(model: str | None, mod: str | None = None, small: bool = False) -> str | None:
    car = cars.get(model) or next((c for c in cars.CARS if c.catalog == model), None)  # старые записи — имя каталога
    if car is None:
        return None
    key = MOD_PHOTOS.get((car.name, mod)) or CAR_PHOTOS.get(car.name)
    name = f"{key}{'-s' if small else ''}.webp" if key else None
    return f"/static/cars/{name}" if name and (STATIC / "cars" / name).exists() else None


async def profile_json(session: AsyncSession, c: Client) -> dict:
    user, lang = c.user, c.lang
    staff_dealer = await session.get(Dealer, c.staff_dealer_id) if c.staff_dealer_id else None
    car = None
    if user.car_model:
        car = {"model": user.car_model, "mod": user.car_modification, "color": user.car_color,
               "mod_name": cars.mod_name(user.car_modification, lang), "color_name": cars.color_name(user.car_color, lang),
               "hex": COLOR_HEX.get(user.car_color or ""),
               "photo": car_photo(user.car_model, user.car_modification, small=True)}
    return {"name": " ".join(filter(None, [user.first_name, user.last_name])) or None, "phone": user.phone,
            "region": {"id": user.region_id, "name": localized_name(user.region, lang)},
            "lang": lang or "ru", "languages": [{"code": code, "name": i18n.t(code, "language_name")} for code in LANGUAGES],
            "car": car, "staff_dealer": staff_dealer.name if staff_dealer else None,
            "vin": user.car_vin, "vin_check": bool(user.car_vin) and check_digit_ok(user.car_vin)}


class LanguageBody(BaseModel):
    code: str = Field(min_length=2, max_length=2)


class RegionBody(BaseModel):
    region_id: int = Field(gt=0)


class VinBody(BaseModel):
    vin: str = Field(default="", max_length=40)  # пусто — удалить VIN


class CarBody(BaseModel):
    model: str = Field(max_length=64)
    mod: str | None = Field(default=None, max_length=32)
    color: str = Field(max_length=32)


class AddBody(BaseModel):
    stock_id: int = Field(gt=0)
    dealer_id: int | None = Field(default=None, gt=0)  # предзаказ: у какого дилера заберёт


class ChangeBody(BaseModel):
    item_id: int = Field(gt=0)
    delta: int = Field(ge=-1, le=1)


class ItemBody(BaseModel):
    item_id: int = Field(gt=0)


def register_api(app: FastAPI) -> None:
    @app.get("/api/me")
    async def me(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        user, lang = c.user, c.lang
        return {"lang": lang or "ru", "name": user.first_name or "", "region": localized_name(user.region, lang),
                "car": cars.car_text(user, lang) if not c.full else None, "full": c.full,
                "car_photo": car_photo(user.car_model, user.car_modification) if not c.full else None,
                "car_model": user.car_model if not c.full else None,
                "cart": await CartRepository(session).total_qty(user), "t": ui_texts(lang)}

    @app.get("/api/catalog")
    async def catalog(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        """Модели и категории с числом деталей, которые можно заказать в регионе клиента."""
        lang, repo = c.lang, CatalogRepository(session, c.user.region_id)
        allowed = c.models()
        models = [m for m in await repo.list_models(lang) if allowed is None or m.name_ru in allowed]
        result = []
        for model in models:
            mine = not c.full and model.name_ru == cars.catalog_model(c.user)
            counts = await repo.count_parts_by_node(model.id)
            nodes = await repo.list_nodes(model.id, lang, cars.carsale_code(c.user) if mine else None)
            result.append({"id": model.id, "name": localized_name(model, lang), "mine": mine,
                           "other": model.name_ru == ALL_MODELS[0],
                           "nodes": [{"id": n.id, "name": localized_name(n, lang), "count": counts.get(n.id, 0),
                                      "icon": ICONS.get(n.name_ru, "other")} for n in nodes]})
        result.sort(key=lambda m: (not m["mine"], m["other"]))  # своя модель — первой, «Прочее» — последней
        return {"models": result}

    @app.get("/api/parts")
    async def parts(model_id: int, node_id: int, offset: int = 0,
                    c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        repo = CatalogRepository(session, c.user.region_id)
        model = await repo.get_model(model_id)
        allowed = c.models()
        if model is None or (allowed is not None and model.name_ru not in allowed):
            raise HTTPException(404, "not_found")
        mod = cars.carsale_code(c.user) if not c.full and model.name_ru == cars.catalog_model(c.user) else None
        offset = max(0, offset)
        total = await repo.count_parts(model_id, node_id, mod)
        items = await repo.list_parts(model_id, node_id, c.lang, offset, PAGE, mod)
        return {"total": total, "offset": offset, "items": await briefs(session, items, c)}

    @app.get("/api/search")
    async def search(q: str = "", c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        q = " ".join(q.split())[:64]
        if len(q.replace(" ", "")) < 2:
            return {"q": q, "items": []}
        found = await CatalogRepository(session, c.user.region_id).search(q, c.lang, c.models(), limit=PAGE)
        return {"q": q, "items": await briefs(session, found, c)}

    @app.get("/api/part/{part_id}")
    async def part(part_id: int, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        lang, stocks = c.lang, StockRepository(session)
        item = await CatalogRepository(session).get_part(part_id)
        if item is None:
            raise HTTPException(404, "not_found")
        offers = [o for o in await stocks.offers_in_region(item.id, c.user.region_id) if o.quantity > 0]
        preorder = None
        if not offers:
            stock, dealers = await stocks.warehouse_offer(item.id), await stocks.pickup_dealers(c.user.region_id)
            if stock is not None and dealers:
                preorder = {"stock_id": stock.id, "price": money(stock.price, lang), "qty": stock.quantity,
                            "days": region_days(c.user.region, lang), "dealers": [dealer_json(d) for d in dealers]}
        in_cart = {i.stock_id: i.quantity for i in await CartRepository(session).items(c.user)}
        description = getattr(item, f"description_{lang}", None) or item.description_ru
        return {
            "id": item.id, "name": localized_name(item, lang), "number": item.part_number, "photo": item.photo,
            "icon": ICONS.get(item.node.name_ru, "other"), "pic": picture_key(item.name_en, item.name_ru),
            "model": localized_name(item.model, lang), "node": localized_name(item.node, lang),
            "description": description, "region": localized_name(c.user.region, lang),
            "offers": [{"stock_id": o.id, "price": money(o.price, lang), "qty": o.quantity,
                        "in_cart": in_cart.get(o.id, 0), "dealer": dealer_json(o.dealer)} for o in offers],
            "preorder": preorder and {**preorder, "in_cart": in_cart.get(preorder["stock_id"], 0)},
            "elsewhere": 0 if offers or preorder else await stocks.regions_elsewhere(item.id, c.user.region_id),
        }

    @app.get("/api/cart")
    async def cart(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        return await cart_json(session, c)

    @app.post("/api/cart/add")
    async def cart_add(body: AddBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        stocks = StockRepository(session)
        stock = await stocks.get(body.stock_id)
        pickup = await stocks.get_dealer(body.dealer_id) if body.dealer_id else None
        if stock is None or (body.dealer_id and pickup is None):
            raise HTTPException(404, "not_found")
        ok, qty = await CartRepository(session).add(c.user, stock, pickup)
        return {"ok": ok, "qty": qty, "cart": await CartRepository(session).total_qty(c.user)}

    @app.post("/api/cart/change")
    async def cart_change(body: ChangeBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        ok = await CartRepository(session).change(c.user, body.item_id, body.delta)
        return {"ok": ok, **await cart_json(session, c)}

    @app.post("/api/cart/remove")
    async def cart_remove(body: ItemBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        await CartRepository(session).remove(c.user, body.item_id)
        return {"ok": True, **await cart_json(session, c)}

    @app.post("/api/checkout")
    async def checkout(request: Request, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        """Корзина → заказы (как «✅ Подтвердить заказ» в боте). Карточку заказа клиент получает и в чат."""
        from app.keyboards.orders import order_keyboard
        from app.services.notify import notify_new_order, send

        repo = OrderRepository(session)
        try:
            created = await repo.create_from_cart(c.user)
            await session.commit()
        except CheckoutError as e:
            await session.commit()  # изменений не было — снимаем блокировку остатков
            return JSONResponse({"problems": stock_problems_text(e.problems, c.lang)}, status_code=409)
        if not created:
            raise HTTPException(409, "empty")
        bot, settings = request.app.state.bot, request.app.state.settings
        for order in created:
            await session.refresh(order)
            await send(bot, c.user.telegram_id, orders_service.order_text(order, c.lang), order_keyboard(order, c.lang))
            await notify_new_order(bot, settings, session, order)
        logger.info("Mini App: user %s created orders %s", c.user.telegram_id, [o.id for o in created])
        return {"orders": [order_json(o, c.lang) for o in created]}

    @app.get("/api/orders")
    async def orders(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        return {"orders": [order_json(o, c.lang) for o in await OrderRepository(session).for_user(c.user, 20)]}

    # ---------- профиль: то же, что «👤 Профиль» в боте ----------

    @app.get("/api/profile")
    async def profile(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        return await profile_json(session, c)

    @app.get("/api/regions")
    async def regions(c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        return {"regions": [{"id": r.id, "name": localized_name(r, c.lang)}
                            for r in await RegionRepository(session).list_active()]}

    @app.get("/api/cars")
    async def car_models(c: Client = Depends(client)):
        lang = c.lang
        result = []
        for name in cars.models():
            mods = cars.modifications(name)
            result.append({
                "model": name, "photo": car_photo(name, small=True),
                "mods": [{"key": m, "name": cars.mod_name(m, lang), "photo": car_photo(name, m, small=True)} for m in mods],
                "colors": {m: [{"key": k, "name": cars.color_name(k, lang), "hex": COLOR_HEX.get(k)}
                               for k in cars.colors(name, m or None)] for m in (mods or [""])},
            })
        return {"cars": result}

    @app.post("/api/profile/language")
    async def set_language(body: LanguageBody, request: Request, c: Client = Depends(client),
                           session: AsyncSession = Depends(get_session)):
        """Язык меняем и в витрине, и в боте: нижнее меню чата сразу приходит на новом языке."""
        from app.keyboards.main import main_reply_keyboard
        from app.services.notify import send

        if body.code not in LANGUAGES:
            raise HTTPException(422, "bad_language")
        await UserRepository(session).set_language(c.user, body.code)
        await send(request.app.state.bot, c.user.telegram_id, i18n.t(body.code, "language_saved"),
                   main_reply_keyboard(body.code, staff=c.full))
        return await profile_json(session, c)

    @app.post("/api/profile/region")
    async def set_region(body: RegionBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        region = await RegionRepository(session).get_active(body.region_id)
        if region is None:
            raise HTTPException(404, "not_found")
        await UserRepository(session).set_region(c.user, region)
        return await profile_json(session, c)

    @app.post("/api/profile/car")
    async def set_car(body: CarBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        mods = cars.modifications(body.model)
        if body.model not in cars.models():
            raise HTTPException(422, "bad_model")
        if (body.mod or None) not in (mods or [None]):  # у модели с комплектациями она обязательна
            raise HTTPException(422, "bad_mod")
        if body.color not in cars.colors(body.model, body.mod or None):
            raise HTTPException(422, "bad_color")
        await UserRepository(session).set_car(c.user, model=body.model, modification=body.mod or None, color=body.color)
        return await profile_json(session, c)

    # ---------- VIN: фото → номер, затем клиент проверяет и сохраняет ----------

    @app.post("/api/vin/scan")
    async def vin_scan(request: Request, photo: UploadFile = File(...), c: Client = Depends(client)):
        if not request.app.state.scan_limiter.allow(c.user.telegram_id):
            raise HTTPException(429, "too_many")
        data = await photo.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "too_big")
        async with request.app.state.scan_slots:
            vin, method = await asyncio.to_thread(read_vin, data)  # фото не сохраняем — только читаем номер
        return {"vin": vin, "method": method, "check_ok": bool(vin) and check_digit_ok(vin)}

    @app.post("/api/profile/vin")
    async def set_vin(body: VinBody, c: Client = Depends(client), session: AsyncSession = Depends(get_session)):
        vin = normalize(body.vin)
        if vin and not is_valid(vin):
            raise HTTPException(422, "bad_vin")
        await UserRepository(session).set_car(c.user, vin=vin or None)
        return await profile_json(session, c)

    @app.get(URL_PREFIX + "{name}")
    async def part_photo(name: str, session: AsyncSession = Depends(get_session)):
        """Фото детали из каталога JAC (хранится в базе). Имя — md5 картинки, поэтому кэшируем навсегда."""
        m = NAME_RE.fullmatch(name)
        data = await image_bytes(session, m.group(1)) if m else None
        if data is None:
            raise HTTPException(404, "not_found")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

