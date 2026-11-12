"""Витрина в Telegram (Mini App): подпись Telegram, доступ, каталог, корзина, предзаказ и заказ через витрину."""
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import Settings
from app.database.models import Order, Part, Stock, User
from app.miniapp.server import check_init_data, create_app
from tests.test_preorder import factory, sync, wh  # noqa: F401 — база: Ташкент (2 дилера), Самарканд, Хорезм
from tests.test_sync import row

TOKEN = "123456:TEST-token"


def init_data(telegram_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    """Подписать initData так же, как это делает Telegram (HMAC-SHA256 ключом из токена бота)."""
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAH",
              "user": json.dumps({"id": telegram_id, "first_name": "Азиз", "language_code": "ru"}, ensure_ascii=False)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_init_data_signature():
    assert check_init_data(init_data(11), TOKEN) == 11
    for bad in (init_data(11, token="999:other"), init_data(11).replace("11", "12", 1), "", "hash=abc"):
        with pytest.raises(HTTPException) as e:
            check_init_data(bad, TOKEN)
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:  # открыта больше суток назад
        check_init_data(init_data(11, auth_date=int(time.time()) - 2 * 86400), TOKEN)
    assert e.value.detail == "expired"


@pytest.fixture
async def shop(factory):  # noqa: F811
    await sync(factory, [row(2, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «China Group»", model="M4", price="85000"),
                         row(5, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «ASIAMOTOR»", model="M4", price="89000"),
                         row(1, "5206100P3010", "FRONT WINDSHIELD", "OOO «China Group»", model="T8-P30BF")],
               [wh(4, "3608100V670001", "BSM")])
    bot = MagicMock()
    bot.send_message, bot.session.close = AsyncMock(), AsyncMock()
    app = create_app(Settings(bot_token=TOKEN, admin_ids={99}, database_url=""), session_factory=factory, bot=bot)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://shop.test") as client:
            client.headers["X-Telegram-Init-Data"] = init_data(11)  # клиент 1: JAC M4 Luxe, Ташкент
            yield client, bot, factory


async def test_page_and_access(shop):
    client, _, factory = shop
    page = await client.get("/", headers={"X-Telegram-Init-Data": ""})
    assert page.status_code == 200 and "/static/app.js?v=" in page.text and "{{v}}" not in page.text
    assert "frame-ancestors https://web.telegram.org" in page.headers["content-security-policy"]
    assert (await client.get("/static/app.css")).status_code == 200
    assert (await client.get("/api/me", headers={"X-Telegram-Init-Data": ""})).status_code == 401
    unknown = await client.get("/api/me", headers={"X-Telegram-Init-Data": init_data(5555)})
    assert unknown.status_code == 403 and unknown.json() == {"error": "register"}  # не зарегистрирован в боте
    async with factory() as s:
        (await s.get(User, 1)).blocked = True
        await s.commit()
    assert (await client.get("/api/me")).json() == {"error": "blocked"}


async def test_catalog_search_and_part(shop):
    client, _, _ = shop
    me = (await client.get("/api/me")).json()
    assert me["car"] == "JAC M4 Luxe" and me["region"] == "Ташкент" and me["t"]["add"] == "Добавить в корзину"
    assert me["cart"] == 0 and me["full"] is False

    models = (await client.get("/api/catalog")).json()["models"]
    assert [m["name"] for m in models] == ["JAC M4 Luxe"]  # деталь от T8 клиенту M4 не показываем
    nodes = {n["name"]: n for n in models[0]["nodes"]}
    assert nodes["ТО и расходники"]["count"] == 1 and nodes["ТО и расходники"]["icon"] == "service"
    assert nodes["Электрика и электроника"]["count"] == 1  # BSM — только на складе, но заказать можно

    node = nodes["ТО и расходники"]
    parts = (await client.get(f"/api/parts?model_id={models[0]['id']}&node_id={node['id']}")).json()
    [oil] = parts["items"]
    assert oil["name"] == "Масляный фильтр" and oil["price"] == "85 000 сум" and oil["dealers"] == 2
    assert oil["status"] == "stock" and oil["pic"] == "oil_filter"

    found = (await client.get("/api/search?q=3608100")).json()["items"]
    assert found[0]["status"] == "preorder" and found[0]["days"] == "1–2 дня"
    assert (await client.get("/api/search?q=windshield")).json()["items"] == []
    assert (await client.get("/api/search?q=a")).json()["items"] == []  # короче 2 символов

    card = (await client.get(f"/api/part/{oil['id']}")).json()
    assert [o["dealer"]["name"] for o in card["offers"]] == ["OOO «China Group»", "OOO «ASIAMOTOR»"]
    assert card["preorder"] is None and card["offers"][0]["price"] == "85 000 сум"
    bsm = (await client.get(f"/api/part/{found[0]['id']}")).json()
    assert bsm["offers"] == [] and len(bsm["preorder"]["dealers"]) == 2 and bsm["preorder"]["days"] == "1–2 дня"
    assert (await client.get("/api/part/99999")).status_code == 404


async def test_cart_preorder_and_checkout(shop):
    client, bot, factory = shop
    bsm_id = (await client.get("/api/search?q=3608100")).json()["items"][0]["id"]
    pre = (await client.get(f"/api/part/{bsm_id}")).json()["preorder"]
    asia = next(d for d in pre["dealers"] if d["name"] == "OOO «ASIAMOTOR»")
    added = (await client.post("/api/cart/add", json={"stock_id": pre["stock_id"], "dealer_id": asia["id"]})).json()
    assert added == {"ok": True, "qty": 1, "cart": 1}
    no_dealer = (await client.post("/api/cart/add", json={"stock_id": pre["stock_id"]})).json()
    assert no_dealer["ok"] is False  # склад — только с дилером выдачи

    oil_id = (await client.get("/api/search?q=фильтр")).json()["items"][0]["id"]
    best = (await client.get(f"/api/part/{oil_id}")).json()["offers"][0]
    for expected in (True, True, False):  # у China Group 2 шт. — третью не добавить
        assert (await client.post("/api/cart/add", json={"stock_id": best["stock_id"]})).json()["ok"] is expected

    cart = (await client.get("/api/cart")).json()
    assert cart["count"] == 3 and cart["orders"] == 2 and cart["total"] == "1 601 911 сум"
    preorder_line = next(i for i in cart["items"] if i["preorder"])
    assert preorder_line["dealer"] == "OOO «ASIAMOTOR»" and preorder_line["days"] == "1–2 дня"
    oil_line = next(i for i in cart["items"] if not i["preorder"])
    changed = (await client.post("/api/cart/change", json={"item_id": oil_line["id"], "delta": 1})).json()
    assert changed["ok"] is False  # больше остатка нельзя
    assert (await client.post("/api/cart/change", json={"item_id": oil_line["id"], "delta": 5})).status_code == 422

    result = (await client.post("/api/checkout")).json()
    assert len(result["orders"]) == 2
    pre_order = next(o for o in result["orders"] if o["preorder"])
    assert pre_order["dealer"]["name"] == "OOO «ASIAMOTOR»" and pre_order["steps"][1]["label"] == "Едет к дилеру"
    # клиенту — карточка каждого заказа в чат, администратору — «новый заказ»
    sent_to = [c.args[0] for c in bot.send_message.call_args_list]
    assert sent_to.count(11) == 2 and sent_to.count(99) == 2
    assert (await client.get("/api/cart")).json()["items"] == []
    orders = (await client.get("/api/orders")).json()["orders"]
    assert {o["id"] for o in orders} == {o["id"] for o in result["orders"]}
    assert (await client.post("/api/checkout")).status_code == 409  # корзина пуста

    async with factory() as s:  # заказ — тот же, что из бота: резерв со склада, дилер выдачи
        order = await s.get(Order, pre_order["id"])
        assert order.preorder and order.source_dealer.is_warehouse
        assert (await s.scalar(select(Stock).join(Part).where(Part.part_number == "3608100V670001"))).quantity == 3


async def test_cart_of_other_client_is_untouchable(shop):
    client, _, factory = shop
    oil_id = (await client.get("/api/search?q=фильтр")).json()["items"][0]["id"]
    best = (await client.get(f"/api/part/{oil_id}")).json()["offers"][0]
    await client.post("/api/cart/add", json={"stock_id": best["stock_id"]})
    item_id = (await client.get("/api/cart")).json()["items"][0]["id"]
    other = {"X-Telegram-Init-Data": init_data(12)}  # клиент 2 (Самарканд)
    await client.post("/api/cart/remove", json={"item_id": item_id}, headers=other)
    await client.post("/api/cart/change", json={"item_id": item_id, "delta": -1}, headers=other)
    assert (await client.get("/api/cart")).json()["count"] == 1


def test_shop_button_only_with_https_url(monkeypatch):
    from app.handlers.catalog import shop_row
    monkeypatch.setenv("MINIAPP_URL", "http://insecure.example")
    assert shop_row("ru") == []
    monkeypatch.setenv("MINIAPP_URL", "https://jac.tail1234.ts.net/")
    [[button]] = shop_row("ru")
    assert button.text == "🛍 Открыть витрину" and button.web_app.url == "https://jac.tail1234.ts.net/"


# ---------- профиль ----------

async def test_profile_view_and_language(shop):
    client, bot, _ = shop
    p = (await client.get("/api/profile")).json()
    assert p["phone"] == "+998901112233" and p["region"]["name"] == "Ташкент" and p["lang"] == "ru"
    assert [l["name"] for l in p["languages"]] == ["Русский", "O‘zbekcha", "English"]
    assert p["car"]["model"] == "JAC M4 Luxe" and p["staff_dealer"] is None
    assert [r["name"] for r in (await client.get("/api/regions")).json()["regions"]] == ["Ташкент", "Самарканд", "Хорезм"]

    p = (await client.post("/api/profile/language", json={"code": "uz"})).json()
    assert p["lang"] == "uz" and (await client.get("/api/me")).json()["t"]["tab_profile"] == "Profil"
    # нижнее меню бота сразу приходит на новом языке
    chat_id, text = bot.send_message.call_args.args[:2]
    assert chat_id == 11 and "O‘zbekcha" in text and bot.send_message.call_args.kwargs["reply_markup"] is not None
    assert (await client.post("/api/profile/language", json={"code": "de"})).status_code == 422


async def test_profile_region_clears_foreign_cart(shop):
    client, _, factory = shop
    oil_id = (await client.get("/api/search?q=фильтр")).json()["items"][0]["id"]
    best = (await client.get(f"/api/part/{oil_id}")).json()["offers"][0]
    await client.post("/api/cart/add", json={"stock_id": best["stock_id"]})
    assert (await client.get("/api/cart")).json()["count"] == 1
    p = (await client.post("/api/profile/region", json={"region_id": 2})).json()
    assert p["region"]["name"] == "Самарканд"
    assert (await client.get("/api/cart")).json()["count"] == 0  # ташкентский дилер — не для Самарканда
    assert (await client.post("/api/profile/region", json={"region_id": 999})).status_code == 404


async def test_profile_car(shop):
    client, _, _ = shop
    models = {c["model"]: c for c in (await client.get("/api/cars")).json()["cars"]}
    assert [m["key"] for m in models["JAC M3"]["mods"]] == ["passenger", "van"]
    assert models["JAC M3"]["colors"]["van"][0] == {"key": "white", "name": "Белый", "hex": "#f4f4f4"}
    assert models["JAC T8"]["mods"] == [] and "" in models["JAC T8"]["colors"]

    p = (await client.post("/api/profile/car", json={"model": "JAC M3", "mod": "van", "color": "white"})).json()
    assert p["car"] == {"model": "JAC M3", "mod": "van", "color": "white", "mod_name": "VAN (фургон)",
                        "color_name": "Белый", "hex": "#f4f4f4", "photo": "/static/cars/m3-van-s.webp"}
    assert (await client.get("/api/me")).json()["car"] == "JAC M3 · VAN (фургон) · Белый"
    for bad in ({"model": "JAC M3", "color": "white"},                       # у M3 комплектация обязательна
                {"model": "JAC T8", "color": "red"},                         # такого цвета у T8 нет
                {"model": "Tesla", "color": "white"}):
        assert (await client.post("/api/profile/car", json=bad)).status_code == 422
    assert (await client.post("/api/profile/car", json={"model": "JAC T8", "color": "gray"})).json()["car"]["mod"] is None


async def test_model_photos(shop):
    client, _, _ = shop
    me = (await client.get("/api/me")).json()
    assert me["car_model"] == "JAC M4 Luxe" and me["car_photo"] == "/static/cars/m4.webp"  # старая запись — имя каталога
    photo = await client.get(me["car_photo"])
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/webp"
    models = {c["model"]: c for c in (await client.get("/api/cars")).json()["cars"]}
    assert models["JAC RF8"]["photo"] == "/static/cars/rf8-s.webp"
    assert {m["key"]: m["photo"] for m in models["JAC M3"]["mods"]} == {
        "passenger": "/static/cars/m3-s.webp", "van": "/static/cars/m3-van-s.webp"}  # у фургона своё фото
    assert all(m["photo"] for m in models.values())  # фото есть у всех 7 моделей, включая T9


async def test_vin_scan_and_save(shop):
    from tests.test_vin import VIN, barcode_png, zxingcpp

    client, bot, factory = shop
    assert (await client.get("/api/profile")).json()["vin"] is None
    # фото наклейки со штрих-кодом → номер; фото не сохраняется
    found = (await client.post("/api/vin/scan", files={"photo": ("vin.png", barcode_png(VIN, zxingcpp.BarcodeFormat.Code128),
                                                                  "image/png")})).json()
    assert found == {"vin": VIN, "method": "barcode", "check_ok": True}
    junk = (await client.post("/api/vin/scan", files={"photo": ("x.jpg", b"not a photo", "image/jpeg")})).json()
    assert junk == {"vin": None, "method": None, "check_ok": False}
    big = await client.post("/api/vin/scan", files={"photo": ("big.jpg", b"0" * (10 * 1024 * 1024 + 1), "image/jpeg")})
    assert big.status_code == 413 and big.json() == {"error": "too_big"}
    assert (await client.post("/api/vin/scan")).status_code == 422  # без фото

    # клиент сверил и сохранил: пробелы и маленькие буквы не мешают, кривой номер — 422
    p = (await client.post("/api/profile/vin", json={"vin": " lj1 2ekr1 7n4000123 "})).json()
    assert p["vin"] == VIN and p["vin_check"] is True
    assert (await client.post("/api/profile/vin", json={"vin": "LJ12EKR17N40001"})).json() == {"error": "bad_vin"}
    p = (await client.post("/api/profile/vin", json={"vin": "LJ12EKR15N4000123"})).json()
    assert p["vin"] == "LJ12EKR15N4000123" and p["vin_check"] is False  # сохраняем, но витрина попросит перепроверить
    await client.post("/api/profile/vin", json={"vin": VIN})

    # VIN попадает в заказ: администратор и дилер видят его в уведомлении и в панели
    oil_id = (await client.get("/api/search?q=фильтр")).json()["items"][0]["id"]
    best = (await client.get(f"/api/part/{oil_id}")).json()["offers"][0]
    await client.post("/api/cart/add", json={"stock_id": best["stock_id"]})
    order_id = (await client.post("/api/checkout")).json()["orders"][0]["id"]
    async with factory() as s:
        assert (await s.get(Order, order_id)).car == f"JAC M4 Luxe · VIN {VIN}"
    admin_text = next(c.args[1] for c in bot.send_message.call_args_list if c.args[0] == 99)
    assert VIN in admin_text

    # другая модель — VIN от прошлой машины сбрасывается; «Удалить VIN» — тоже
    p = (await client.post("/api/profile/car", json={"model": "JAC T8", "color": "gray"})).json()
    assert p["vin"] is None
    await client.post("/api/profile/vin", json={"vin": VIN})
    assert (await client.post("/api/profile/vin", json={"vin": ""})).json()["vin"] is None


async def test_vin_scan_rate_limit(shop):
    client, _, _ = shop
    codes = [(await client.post("/api/vin/scan", files={"photo": ("x.jpg", b"x", "image/jpeg")})).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429  # не больше 20 фото в минуту


async def test_epc_photo_in_shop(shop):
    from app.database.models import EpcImage, EpcPhoto
    from app.services import part_photos
    from tests.test_part_photos import MD5_A, png

    client, _, factory = shop
    async with factory() as s:
        s.add(EpcImage(md5=MD5_A, data=part_photos.to_jpeg(png("green"))))
        s.add(EpcPhoto(key="1017100GD050", part_number="1017100GD050", image=MD5_A))
        await s.flush()
        assert await part_photos.apply_to_parts(s) == 1  # масляный фильтр M4
        await s.commit()
    item = (await client.get("/api/search?q=1017100")).json()["items"][0]
    assert item["photo"] == f"/media/parts/{MD5_A}.jpg"
    assert (await client.get(f"/api/part/{item['id']}")).json()["photo"] == item["photo"]
    photo = await client.get(item["photo"], headers={"X-Telegram-Init-Data": ""})  # картинке подпись Telegram не нужна
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert "immutable" in photo.headers["cache-control"]
    assert (await client.get("/media/parts/" + "0" * 32 + ".jpg")).status_code == 404
    assert (await client.get("/media/parts/x.png")).status_code == 404
