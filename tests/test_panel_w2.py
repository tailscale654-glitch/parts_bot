"""Веб-панель, этап 2: дилеры, клиенты (блокировка), каталог (переводы), загрузка Excel."""
import re
from types import SimpleNamespace

from aiogram.types import Update
from sqlalchemy import select

from app.database.models import Dealer, DealerStaff, Part, PartTranslation, Stock, User
from app.middlewares.db import DbSessionMiddleware
from app.services.part_names import has_translation, translate
from app.services.roles import can
from tests.test_offers_cart import db  # noqa: F401
from tests.test_panel import _SessionCtx, csrf_of, env, login  # noqa: F401
from tests.test_warehouse_import import make_export, row


async def post(client, url, data, page="/"):
    data = {"csrf": await csrf_of(client, page), **data}
    return await client.post(url, data=data)


def test_permissions():
    assert can("manager", "upload") and can("manager", "catalog.edit") and not can("manager", "staff")
    assert can("operator", "catalog.view") and not can("operator", "dealers.view")
    assert can("viewer", "dealers.view") and not can("viewer", "clients.edit") and not can("viewer", "upload")


async def test_operator_limits(env):
    await login(env.client, *env.creds["operator"])
    html = (await env.client.get("/")).text
    assert "/catalog" in html and "/dealers" not in html and "/upload" not in html
    assert (await env.client.get("/dealers")).status_code == 403
    assert (await env.client.get("/upload")).status_code == 403
    assert (await env.client.get("/catalog")).status_code == 200
    r = await post(env.client, "/clients/2/blocked", {"blocked": "1"})
    assert r.status_code == 403


async def test_dealers_edit_toggle_invite_staff(env):
    await login(env.client, *env.creds["admin"])
    (await env.db.get(Dealer, 4)).code = "SMK-01"
    await env.db.commit()
    html = (await env.client.get("/dealers?q=smk")).text  # поиск по коду (и названию, телефону, адресу)
    assert "JAC Самарканд" in html and "JAC Ташкент №2" not in html
    html = (await env.client.get("/dealers?region_id=1")).text
    assert "JAC Самарканд" not in html and "JAC Ташкент №2" in html

    r = await post(env.client, "/dealers/2", {"phone": "+998 71 200 00 00", "address": "ул. Навои, 1", "region_id": "2"})
    assert r.status_code == 303
    dealer = await env.db.get(Dealer, 2)
    await env.db.refresh(dealer)
    assert dealer.phone == "+998 71 200 00 00" and dealer.region_id == 2

    await post(env.client, "/dealers/2/enabled", {"enabled": "0"})
    await env.db.refresh(dealer)
    assert dealer.enabled is False

    r = await post(env.client, "/dealers/2/invite", {})
    assert "start%3Ddealer_" in r.headers["location"] or "start=dealer_" in r.headers["location"]
    html = (await env.client.get(r.headers["location"])).text
    assert re.search(r"t\.me/jac_parts_bot\?start=dealer_[\w-]+", html)

    env.db.add(DealerStaff(dealer_id=2, user_id=2))
    await env.db.commit()
    staff = await env.db.scalar(select(DealerStaff))
    assert "Убрать" in (await env.client.get("/dealers/2")).text
    assert (await post(env.client, f"/dealers/1/staff/{staff.id}/remove", {})).status_code == 404  # чужой дилер
    await post(env.client, f"/dealers/2/staff/{staff.id}/remove", {})
    assert await env.db.scalar(select(DealerStaff)) is None


async def test_clients_search_message_block(env):
    await login(env.client, *env.creds["admin"])
    html = (await env.client.get("/clients?q=7654321")).text
    assert "/clients/2" in html and "/clients/1\"" not in html
    assert f"/orders/{env.order.id}" in (await env.client.get("/clients/1")).text  # заказ клиента

    await post(env.client, "/clients/2/message", {"text": "Здравствуйте!"})
    assert env.bot.sent[-1][0] == 2 and "Здравствуйте!" in env.bot.sent[-1][1]

    await post(env.client, "/clients/2/blocked", {"blocked": "1"})
    user = await env.db.get(User, 2)
    await env.db.refresh(user)
    assert user.blocked is True
    assert "заблокирован" in (await env.client.get("/clients?who=blocked")).text

    r = await post(env.client, "/clients/1/blocked", {"blocked": "1"})  # админ из ADMIN_IDS
    assert r.status_code == 400


async def test_blocked_user_ignored_by_bot(db):  # noqa: F811
    user = await db.get(User, 2)
    user.blocked = True
    await db.commit()
    middleware = DbSessionMiddleware(lambda: _SessionCtx(db))
    called = []

    async def handler(event, data):
        called.append(data["user"].id)

    settings = SimpleNamespace(admin_ids={1})
    update = Update(update_id=1)
    for tg_id in (2, 1):
        tg = SimpleNamespace(id=tg_id, is_bot=False, username=None, first_name="X", last_name=None)
        await middleware(handler, update, {"event_from_user": tg, "settings": settings})
    assert called == [1]  # заблокированный (2) — мимо, админ (1) — как обычно


async def test_translation_saved_and_used_by_import(env):
    part = await env.db.get(Part, 1)
    part.name_en, part.name_ru, part.name_uz = "OIL FILTER X", "OIL FILTER X", None
    await env.db.commit()
    await login(env.client, *env.creds["admin"])
    html = (await env.client.get("/catalog?show=untranslated")).text
    assert "101001" in html

    r = await post(env.client, "/catalog/1/translation", {"name_ru": "Фильтр масляный X", "name_uz": "Moy filtri X"})
    assert r.status_code == 303
    await env.db.refresh(part)
    assert (part.name_ru, part.name_uz) == ("Фильтр масляный X", "Moy filtri X")
    tr = await env.db.scalar(select(PartTranslation))
    assert tr.key == "oil filter x"

    overrides = {tr.key: {"ru": tr.name_ru, "uz": tr.name_uz}}
    assert translate("Oil  Filter X.", overrides) == {"ru": "Фильтр масляный X", "en": "Oil  Filter X.", "uz": "Moy filtri X"}
    assert has_translation("OIL FILTER X", overrides) and not has_translation("OIL FILTER X")
    assert "101001" not in (await env.client.get("/catalog?show=untranslated")).text

    offers = (await env.client.get("/catalog/1")).text
    assert "JAC Ташкент №1" in offers


async def test_web_upload_preview_apply(env, tmp_path, monkeypatch):
    from app.panel import server
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path / "up")
    await login(env.client, *env.creds["admin"])
    path = make_export(tmp_path, [
        row(4, "NEW-1", "BRAKE PAD", "У дилера", "A", "M3", 1000, 1200, "JAC Ташкент №1"),
    ])
    token = await csrf_of(env.client, "/upload")
    r = await env.client.post("/upload", data={"csrf": token},
                              files={"file": ("export.xlsx", path.read_bytes(), "application/octet-stream")})
    assert r.status_code == 200 and "складская выгрузка" in r.text and "Применить" in r.text
    assert await env.db.scalar(select(Part).where(Part.part_number == "NEW-1")) is None  # пока ничего не изменилось
    upload_token = re.search(r'name="token" value="(\w+)"', r.text).group(1)

    r = await post(env.client, "/upload/apply", {"token": upload_token, "action": "apply"}, "/upload")
    assert r.status_code == 200 and "Каталог обновлён" in r.text
    part = await env.db.scalar(select(Part).where(Part.part_number == "NEW-1"))
    assert part is not None and part.active
    stock = await env.db.scalar(select(Stock).where(Stock.part_id == part.id))
    assert stock.quantity == 4
    assert not list((tmp_path / "up").iterdir())  # временный файл удалён

    r = await post(env.client, "/upload/apply", {"token": upload_token, "action": "apply"}, "/upload")
    assert r.status_code == 303 and "flash" in r.headers["location"]  # повторно — «файл не найден»


async def test_web_upload_rejects_bad_file(env, tmp_path, monkeypatch):
    from app.panel import server
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path / "up")
    await login(env.client, *env.creds["admin"])
    token = await csrf_of(env.client, "/upload")
    r = await env.client.post("/upload", data={"csrf": token}, files={"file": ("x.csv", b"a,b", "text/csv")})
    assert ".xlsx" in r.text
    r = await env.client.post("/upload", data={"csrf": token}, files={"file": ("x.xlsx", b"not excel", "application/x")})
    assert "не прошёл проверку" in r.text
