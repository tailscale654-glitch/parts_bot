"""CarSale CRM: VIN → проданная машина («Остатки», состояние «Архив»). Сервер CRM — имитация на aiohttp:
те же адреса и ответы, что у crm.carsale.uz (вход, сессия, таблица остатков, 401 без сессии)."""
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.services import carsale_crm
from app.services.carsale_crm import CarsaleCRM, CrmUnavailable, map_color, map_model

VIN = "LJ166A257T4020777"
ROWS = {  # vin_code, model_name, modification_name, color_name, engine_code, produced_date, state
    VIN: [VIN, "JAC JS8", "JAC JS8", "Black", "T3604334", "11.03.2026", "A"],
    "LJ166A339S2205968": ["LJ166A339S2205968", "M3 VAN", "M3 фургон", "White", "S05176139", "", "A"],
    "LJ166B358T2256757": ["LJ166B358T2256757", "JAC Sunray", "Sunray JS16", "White", "T3001373", "", "F"],  # не продана
}


@pytest.mark.parametrize("model, mod, expected", [
    ("JAC M3", "M3 Люкс 2026", ("JAC M3", "passenger")),
    ("M3 VAN", "M3 фургон", ("JAC M3", "van")),
    ("M4LUXE", "M4 Люкс 9 мест", ("JAC M4", None)),
    ("JAC Sunray", "Sunray JS16", ("JAC Sunray", "minibus")),
    ("Sunray  фургон", "JAC Sunray Фургон", ("JAC Sunray", "van")),
    ("JAC T9", "T9 Luxury 4×4", ("JAC T9", None)),
    ("JAC RF8", "RF8 Flagship", ("JAC RF8", None)),
    ("Chevrolet Cobalt", "", (None, None)),
])
def test_map_model(model, mod, expected):
    assert map_model(model, mod) == expected


@pytest.mark.parametrize("color, expected", [
    ("White", "white"), ("Crystal White", "white"), ("Black", "black"), ("Sandalwood Black", "black"),
    ("Silver", "silver"), ("Metallic gray", "metallic_gray"), ("Star gray", "star_gray"),
    ("Quantum Silver Gray", "gray"), ("Oriental Blue", "blue"), ("Red", "red"), ("", None), ("Розовый", None),
])
def test_map_color(color, expected):
    assert map_color(color) == expected


class FakeCRM:
    """Как crm.carsale.uz: без cookie — 401, без id филиала в заголовках — пустой список."""

    def __init__(self):
        self.logins = 0
        self.tables = 0
        self.sessions = set()
        app = web.Application()
        app.router.add_post("/b/core/s$logon", self.logon)
        app.router.add_post("/b/core/m$session", self.session)
        app.router.add_post("/b/ap/stock_list&table", self.table)
        self.app = app

    async def logon(self, request):
        form = await request.post()
        if (form.get("login"), form.get("password")) != ("partsbot", "secret"):
            return web.Response(status=401, text="password_is_incorrect")
        self.logins += 1
        sid = f"s{self.logins}"
        self.sessions.add(sid)
        resp = web.Response(text="#/main")
        resp.set_cookie("biruni_sid", sid)
        return resp

    def authed(self, request):
        return request.cookies.get("biruni_sid") in self.sessions

    async def session(self, request):
        if not self.authed(request):
            return web.Response(status=401, text="ROUTE: Unauthenticated")
        return web.json_response({"user": {"user_id": "3663930", "login": "partsbot"},
                                  "projects": [{"code": "carsale", "filials": [["3641522", "JAC MOTORS TOSHKENT"]]}]})

    async def table(self, request):
        if not self.authed(request):
            return web.Response(status=401, text="ROUTE: Unauthenticated")
        self.tables += 1
        if request.headers.get("filial_id") != "3641522" or request.headers.get("project_code") != "carsale":
            return web.json_response({"count": 0, "data": []})
        p = (await request.json())["p"]
        assert p["column"] == carsale_crm.COLUMNS
        op, (vin_f, state_f) = p["filter"]
        assert op == "and" and vin_f[:2] == ["vin_code", "="] and state_f == ["state", "=", "A"]
        row = ROWS.get(vin_f[2])
        data = [row] if row and row[-1] == "A" else []
        return web.json_response({"count": len(data), "data": data})


@pytest.fixture
async def crm_server():
    fake = FakeCRM()
    server = TestServer(fake.app)
    await server.start_server()
    yield fake, str(server.make_url("/"))
    await server.close()


async def test_find_sold_car(crm_server):
    fake, url = crm_server
    client = CarsaleCRM(url, "partsbot", "secret")
    try:
        car = await client.find_sold(VIN)
        assert (car.model, car.mod, car.color, car.engine, car.trim, car.produced) == \
            ("JAC JS8", None, "black", "T3604334", "JAC JS8", "11.03.2026")
        van = await client.find_sold("LJ166A339S2205968")
        assert (van.model, van.mod, van.color, van.engine) == ("JAC M3", "van", "white", "S05176139")
        assert await client.find_sold("LJ166B358T2256757") is None  # есть в остатках, но не продана
        assert await client.find_sold("LJ1ZZZZZZZZ000000") is None
        tables = fake.tables
        await client.find_sold(VIN)  # повторно — из памяти, CRM не дёргаем
        assert fake.tables == tables and fake.logins == 1

        fake.sessions.clear()  # сессия на стороне CRM истекла → один повторный вход
        client.cache.clear()
        assert (await client.find_sold(VIN)).engine == "T3604334"
        assert fake.logins == 2
    finally:
        await client.close()


async def test_wrong_password_and_not_configured(crm_server):
    _, url = crm_server
    client = CarsaleCRM(url, "partsbot", "wrong")
    try:
        with pytest.raises(CrmUnavailable, match="вход не удался"):
            await client.find_sold(VIN)
    finally:
        await client.close()
    with pytest.raises(CrmUnavailable, match="не настроена"):
        await CarsaleCRM(url, "", "").find_sold(VIN)


async def test_unreachable_crm():
    client = CarsaleCRM("http://127.0.0.1:9", "partsbot", "secret", timeout=2)
    try:
        with pytest.raises(CrmUnavailable):
            await client.find_sold(VIN)
    finally:
        await client.close()


class StubCRM:
    """Подмена клиента CRM для тестов бота и витрины."""

    def __init__(self, cars=None, down=False):
        self.cars, self.down, self.asked = cars or {}, down, []

    async def find_sold(self, vin):
        self.asked.append(vin)
        if self.down:
            raise CrmUnavailable("нет связи")
        return self.cars.get(vin)


def sold(vin=VIN, **kw):
    row = dict(zip(carsale_crm.COLUMNS, ROWS.get(vin, [vin, "JAC JS8", "JAC JS8", "Black", "T3604334", "", "A"])))
    row.update(kw)
    return carsale_crm.sold_car(row)


def test_sold_car_keeps_only_known_colors():
    car = sold(color_name="Розовый")
    assert car.color is None and car.carsale_color == "Розовый"  # цвет выберет клиент
    assert json.dumps(car.engine) == '"T3604334"'
