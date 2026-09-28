"""Веб-панель, этап 3: статистика, рассылка, настройки (контакты, регионы), журнал действий."""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database.models import AuditLog, Broadcast, Region, User
from app.database.repositories.stats import StatsRepository
from app.panel.charts import bar_chart
from app.services import bot_settings
from app.services import broadcast as broadcast_service
from app.services.roles import can
from tests.test_offers_cart import db  # noqa: F401
from tests.test_panel import csrf_of, env, login  # noqa: F401

TZ = ZoneInfo("Asia/Tashkent")


async def post(client, url, data, page="/"):
    return await client.post(url, data={"csrf": await csrf_of(client, page), **data})


def test_permissions():
    assert can("manager", "broadcast") and can("manager", "settings") and not can("manager", "audit")
    assert can("admin", "audit")
    assert not can("operator", "broadcast") and not can("viewer", "settings") and can("viewer", "stats")


def test_contact_view():
    text, kb = bot_settings.contact_view({}, "ru")
    assert kb is None and "Напишите нам" in text
    text, kb = bot_settings.contact_view({"contact_phone": "+998 71 200 00 00", "contact_telegram": "https://t.me/jac_help",
                                          "contact_hours": "9–18"}, "uz")
    assert "+998 71 200 00 00" in text and "Ish vaqti: 9–18" in text and "@jac_help" in text
    assert kb.inline_keyboard[0][0].url == "https://t.me/jac_help"
    assert bot_settings.telegram_username("@a b") == ""


def test_bar_chart():
    svg = str(bar_chart([("01.09", 3, "3 заказа"), ("02.09", 0, "0"), ("03.09", 7, "7")]))
    assert svg.startswith("<svg") and svg.count('class="bar"') == 3 and "<title>3 заказа</title>" in svg
    assert "Нет данных" in str(bar_chart([]))


async def test_daily_series_has_no_gaps(env):
    since = datetime.now(timezone.utc) - timedelta(days=6)
    days = await StatsRepository(env.db).daily(since, None, TZ)
    assert len(days) in (7, 8) and sum(d.orders for d in days) == 1


async def test_stats_page(env):
    await login(env.client, *env.creds["admin"])
    r = await env.client.get("/stats?period=7")
    assert r.status_code == 200 and "<svg" in r.text and "Заказы по дням" in r.text
    today = datetime.now(TZ).date().isoformat()
    r = await env.client.get(f"/stats?date_from={today}&date_to={today}")
    assert r.status_code == 200 and f"date_from={today}" in r.text
    await login(env.client, *env.creds["operator"])
    assert (await env.client.get("/stats")).status_code == 403


async def test_contacts_and_regions(env):
    await login(env.client, *env.creds["admin"])
    r = await post(env.client, "/settings/contacts", {"contact_phone": "+998 71 1", "contact_telegram": "@ab"}, "/settings")
    assert "flash" in r.headers["location"] and await bot_settings.load(env.db) == {}  # неверный Telegram — не сохранили
    await post(env.client, "/settings/contacts", {"contact_phone": "+998 71 1", "contact_telegram": "@jac_help"}, "/settings")
    values = await bot_settings.load(env.db)
    assert values["contact_phone"] == "+998 71 1" and values["contact_telegram"] == "@jac_help"
    assert "+998 71 1" in (await env.client.get("/settings")).text  # предпросмотр

    await post(env.client, "/settings/regions/2", {"name_ru": "Самарканд", "name_uz": "Samarqand",
                                                   "sort_order": "5"}, "/settings")  # без active — скрыть
    region = await env.db.get(Region, 2)
    await env.db.refresh(region)
    assert region.name_uz == "Samarqand" and region.sort_order == 5 and region.active is False


async def test_broadcast(env, monkeypatch):
    monkeypatch.setattr(broadcast_service, "DELAY", 0)
    blocked = User(id=3, telegram_id=3, language="ru", phone="+998900000003", blocked=True)
    env.db.add(blocked)
    await env.db.commit()
    await login(env.client, *env.creds["admin"])
    assert "Получателей: <b>2</b>" in (await env.client.get("/broadcast")).text  # заблокированный не считается
    assert "Получателей: <b>1</b>" in (await env.client.get("/broadcast?language=en")).text
    assert "Получателей: <b>1</b>" in (await env.client.get("/broadcast?buyers=1")).text  # заказ только у №1

    await post(env.client, "/broadcast/test", {"text": "Проверка"}, "/broadcast")
    assert env.bot.sent[-1] == (1, "Проверка")

    r = await post(env.client, "/broadcast", {"text": "Скидки!"}, "/broadcast")  # без галочки
    assert "flash" in r.headers["location"] and await env.db.scalar(select(Broadcast)) is None

    env.bot.sent.clear()
    await post(env.client, "/broadcast", {"text": "Скидки!", "confirm": "1"}, "/broadcast")
    app = env.client._transport.app
    await asyncio.gather(*app.state.tasks)
    assert sorted(chat for chat, _ in env.bot.sent) == [1, 2]
    b = await env.db.scalar(select(Broadcast))
    await env.db.refresh(b)
    assert (b.status, b.total, b.sent, b.failed, b.audience) == ("done", 2, 2, 0, "все клиенты")
    assert "✅ готово" in (await env.client.get("/broadcast")).text


async def test_audit_log(env):
    await login(env.client, *env.creds["admin"])
    await post(env.client, f"/orders/{env.order.id}/status", {"status": "CONFIRMED"}, f"/orders/{env.order.id}")
    actions = [a.action for a in await env.db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["login", "order.status"]
    html = (await env.client.get("/audit?action=order.status")).text
    assert f"заказ №{env.order.id}" in html and "Вход в панель</td>" not in html
    await login(env.client, *env.creds["operator"])
    assert (await env.client.get("/audit")).status_code == 403
