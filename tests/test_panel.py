"""Веб-панель: вход, роли, заказы, сотрудники (без настоящего Telegram)."""
import re
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.database.models import Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import OrderRepository
from app.database.repositories.web_users import WebUserRepository
from app.panel import server
from app.panel.server import create_app
from tests.test_offers_cart import db  # noqa: F401


class FakeBot:
    def __init__(self):
        self.sent = []
        self.session = SimpleNamespace(close=self._close)

    async def _close(self):
        pass

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text))

    async def me(self):
        return SimpleNamespace(username="jac_parts_bot")


@pytest.fixture
async def env(db):
    """Админ из ADMIN_IDS (telegram 1), оператор (telegram 2), заказ клиента."""
    server.throttle.fails.clear()
    admin, operator = await db.get(User, 1), await db.get(User, 2)
    admin.phone, operator.phone = "+998901234567", "+998907654321"
    await db.commit()
    repo = WebUserRepository(db)
    creds = {"admin": await repo.issue_password(admin, role="viewer"),  # роль из БД не важна — он в ADMIN_IDS
             "operator": await repo.issue_password(operator, role="operator")}
    await CartRepository(db).add(admin, await db.get(Stock, 1))
    order = (await OrderRepository(db).create_from_cart(admin))[0]
    await db.commit()

    bot = FakeBot()
    factory = lambda: db.bind and _SessionCtx(db)  # noqa: E731 — одна и та же тестовая сессия
    app = create_app(Settings(bot_token="1:x", admin_ids={1}, database_url="", web_url="http://10.0.0.5:8080"),
                     session_factory=factory, bot=bot)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://panel")
    yield SimpleNamespace(client=client, creds=creds, order=order, bot=bot, db=db)
    await client.aclose()


class _SessionCtx:
    def __init__(self, s):
        self.s = s

    async def __aenter__(self):
        return self.s

    async def __aexit__(self, *a):
        return False


async def csrf_of(client, url="/login") -> str:
    html = (await client.get(url)).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def login(client, login_, password):
    token = await csrf_of(client)
    return await client.post("/login", data={"login": login_, "password": password, "csrf": token, "next": "/"})


async def test_login_required_and_wrong_password(env):
    r = await env.client.get("/orders")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    r = await login(env.client, env.creds["operator"][0], "wrong")
    assert "Неверный логин или пароль" in r.text
    r = await login(env.client, *env.creds["operator"])
    assert r.status_code == 303 and r.headers["location"] == "/"
    r = await env.client.get("/")
    assert r.status_code == 200 and "Новые заказы" in r.text and str(env.order.id) in r.text


async def test_login_throttle(env):
    for _ in range(5):
        await login(env.client, "nobody", "x")
    r = await login(env.client, *env.creds["operator"])  # даже с верным паролем — подождите
    assert "Слишком много попыток" in r.text


async def test_post_without_csrf_rejected(env):
    await login(env.client, *env.creds["operator"])
    r = await env.client.post(f"/orders/{env.order.id}/status", data={"status": "CONFIRMED"})
    assert r.status_code == 400


async def test_orders_filters_and_status_change(env):
    await login(env.client, *env.creds["operator"])
    html = (await env.client.get("/orders", params={"q": "101001"})).text  # поиск по артикулу
    assert f'/orders/{env.order.id}"' in html and "Масляный фильтр" in html
    html = (await env.client.get("/orders", params={"q": "000000"})).text
    assert "Ничего не найдено" in html
    assert (await env.client.get("/orders", params={"q": "4567"})).text.count(f'/orders/{env.order.id}"') == 1  # телефон

    token = await csrf_of(env.client, f"/orders/{env.order.id}")
    r = await env.client.post(f"/orders/{env.order.id}/status", data={"status": "CONFIRMED", "csrf": token})
    assert r.status_code == 303 and "Подтверждён" in r.headers["location"] or "%" in r.headers["location"]
    await env.db.refresh(env.order)
    assert env.order.status == "CONFIRMED"
    assert any("Подтверждён" in text for _, text in env.bot.sent)  # клиент получил уведомление

    r = await env.client.post(f"/orders/{env.order.id}/message", data={"text": "Приезжайте завтра", "csrf": token})
    assert r.status_code == 303
    assert any("Приезжайте завтра" in text for _, text in env.bot.sent)
    assert "Приезжайте завтра" in (await env.client.get(f"/orders/{env.order.id}")).text

    xlsx = await env.client.get("/orders/export", params={"tab": "work"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


async def test_roles(env):
    await login(env.client, *env.creds["operator"])
    assert (await env.client.get("/staff")).status_code == 403  # оператор не управляет сотрудниками

    viewer_user = await env.db.get(User, 2)
    web = await WebUserRepository(env.db).for_user(viewer_user)
    await WebUserRepository(env.db).set_role(web, "viewer")
    assert (await env.client.get("/orders")).status_code == 303  # роль сменилась → войти заново

    login_, password = env.creds["operator"]
    await login(env.client, login_, password)
    token = await csrf_of(env.client, "/orders")
    r = await env.client.post(f"/orders/{env.order.id}/status", data={"status": "CONFIRMED", "csrf": token})
    assert r.status_code == 403  # наблюдатель только смотрит


async def test_staff_management(env):
    await login(env.client, *env.creds["admin"])
    html = (await env.client.get("/staff")).text
    assert "Сотрудники и роли" in html and env.creds["operator"][0] in html

    token = await csrf_of(env.client, "/staff")
    r = await env.client.post("/staff/invite", data={"role": "manager", "csrf": token})
    link = re.search(r"start%3Dstaff_([\w-]+)", r.headers["location"]).group(1)
    html = (await env.client.get(r.headers["location"])).text
    assert f"https://t.me/jac_parts_bot?start=staff_{link}" in html

    operator = await WebUserRepository(env.db).for_user(await env.db.get(User, 2))
    await env.client.post(f"/staff/{operator.id}/role", data={"role": "manager", "csrf": token})
    await env.db.refresh(operator)
    assert operator.role == "manager"

    await env.client.post(f"/staff/{operator.id}/password", data={"csrf": token})
    assert any(chat == 2 and "Password: <code>" in text for chat, text in env.bot.sent)  # на его языке (en)

    await env.client.post(f"/staff/{operator.id}/active", data={"active": "0", "csrf": token})
    await env.db.refresh(operator)
    assert operator.active is False

    me = await WebUserRepository(env.db).for_user(await env.db.get(User, 1))
    r = await env.client.post(f"/staff/{me.id}/active", data={"active": "0", "csrf": token})
    assert r.status_code == 400  # себя отключить нельзя


async def test_invite_gives_login_with_role(env):
    repo = WebUserRepository(env.db)
    token = await repo.create_invite("operator", await env.db.get(User, 1))
    newcomer = User(telegram_id=555, username="Dilshod_M", language="uz")
    env.db.add(newcomer)
    await env.db.commit()
    login_, password, role = await repo.accept_invite(token, newcomer)
    assert login_ == "dilshod_m" and role == "operator" and len(password) == 12
    r = await login(env.client, login_, password)
    assert r.status_code == 303
