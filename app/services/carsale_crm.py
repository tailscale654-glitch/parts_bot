"""Проданные автомобили из CarSale CRM (crm.carsale.uz): по VIN — модель, комплектация, цвет, номер двигателя.

Где смотрит: «Продажа → Остатки», состояние «Архив» — это все проданные машины.
Как: те же запросы, что делает страница CRM (браузер не нужен):
  1. вход — POST b/core/s$logon (логин и пароль из .env), сервер ставит cookie сессии;
  2. POST b/core/m$session — id пользователя и филиала (без них CRM молча отдаёт пустой список);
  3. POST b/ap/stock_list&table — таблица остатков с фильтром «VIN = … и состояние = Архив».
Сессия истекла (401) — входим заново один раз. Ответы по VIN держим в памяти несколько минут.

Покупателей и цены не читаем — только данные машины.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass

import aiohttp

from app.services import cars

logger = logging.getLogger(__name__)

ARCHIVE = "A"  # «Архив» в колонке «Состояние» — машина продана
COLUMNS = ["vin_code", "model_name", "modification_name", "color_name", "engine_code", "produced_date", "state"]
PAGE_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/plain, */*"}  # как страница CRM
FOUND_TTL, MISSING_TTL = 600, 120  # секунд: найденное меняется редко, «не найдено» — перепроверим скорее


class CrmUnavailable(Exception):
    """CRM не ответила, не пустила или не настроена — VIN проверить нельзя (это не «не найдено»)."""


@dataclass(frozen=True)
class SoldCar:
    vin: str
    model: str | None  # модель в боте (cars.CARS) — None, если такой модели в боте нет
    mod: str | None  # комплектация бота: passenger / van / minibus
    color: str | None  # цвет бота: white / black / …
    engine: str  # номер двигателя
    trim: str  # комплектация как в CarSale («M3 Люкс 2026», «T9 Luxury 4×4»)
    carsale_model: str
    carsale_color: str
    produced: str  # дата выпуска «11.03.2026» (бывает пустой)


# ---------- названия CarSale → модели и цвета бота ----------

def _plain(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


def map_model(model_name: str | None, modification_name: str | None) -> tuple[str | None, str | None]:
    """«M3 VAN» → (JAC M3, van), «M4LUXE» → (JAC M4, None), «Sunray  фургон» → (JAC Sunray, van)."""
    both = f"{_plain(model_name)} | {_plain(modification_name)}"
    van = "фургон" in both or "van" in both
    if "m3" in both:
        return "JAC M3", "van" if van else "passenger"
    if "sunray" in both:
        return "JAC Sunray", "van" if van else "minibus"
    for key, name in (("m4", "JAC M4"), ("t8", "JAC T8"), ("t9", "JAC T9"), ("js8", "JAC JS8"), ("rf8", "JAC RF8")):
        if key in both:
            return name, None
    return None, None


_COLOR_WORDS = (  # порядок важен: «Quantum Silver Gray» — серый, «Metallic gray» — металлик
    ("metallic", "metallic_gray"), ("металлик", "metallic_gray"), ("star", "star_gray"), ("звезд", "star_gray"),
    ("silver gray", "gray"), ("white", "white"), ("бел", "white"), ("black", "black"), ("черн", "black"),
    ("silver", "silver"), ("серебр", "silver"), ("gray", "gray"), ("grey", "gray"), ("сер", "gray"),
    ("red", "red"), ("красн", "red"), ("blue", "blue"), ("син", "blue"),
)


def map_color(color_name: str | None) -> str | None:
    """«Crystal White» → white, «Sandalwood Black» → black, «Oriental Blue» → blue."""
    text = _plain(color_name)
    return next((key for word, key in _COLOR_WORDS if word in text), None) if text else None


def sold_car(row: dict[str, str]) -> SoldCar:
    model, mod = map_model(row.get("model_name"), row.get("modification_name"))
    color = map_color(row.get("color_name"))
    if model and color not in cars.colors(model, mod):
        color = None  # такого цвета у модели в боте нет — клиент выберет сам
    return SoldCar(vin=row["vin_code"], model=model, mod=mod if model and mod in cars.modifications(model) else None,
                   color=color, engine=(row.get("engine_code") or "").strip(),
                   trim=(row.get("modification_name") or "").strip(), carsale_model=(row.get("model_name") or "").strip(),
                   carsale_color=(row.get("color_name") or "").strip(), produced=(row.get("produced_date") or "").strip())


# ---------- клиент ----------

class CarsaleCRM:
    def __init__(self, base_url: str, login: str, password: str, timeout: float = 15):
        self.base = base_url.rstrip("/") + "/"
        self.login, self.password = login, password
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.http: aiohttp.ClientSession | None = None
        self.ids: dict[str, str] | None = None  # user_id, filial_id, project_code после входа
        self.lock = asyncio.Lock()
        self.cache: dict[str, tuple[float, SoldCar | None]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.base and self.login and self.password)

    async def close(self) -> None:
        if self.http is not None:
            await self.http.close()
            self.http = None

    async def _sign_in(self) -> None:
        if self.http is None or self.http.closed:
            # unsafe=True — cookie и с адреса-IP (CRM за прокси/в тестах); адрес CRM задаём мы сами в .env
            self.http = aiohttp.ClientSession(timeout=self.timeout, cookie_jar=aiohttp.CookieJar(unsafe=True),
                                              headers=PAGE_HEADERS)
        self.http.cookie_jar.clear()
        async with self.http.post(self.base + "b/core/s$logon",
                                  data={"login": self.login, "password": self.password}) as r:
            if r.status != 200:
                raise CrmUnavailable(f"вход не удался (HTTP {r.status}) — проверьте CARSALE_CRM_LOGIN и пароль")
        async with self.http.post(self.base + "b/core/m$session", json={}) as r:
            if r.status != 200:
                raise CrmUnavailable(f"нет сессии после входа (HTTP {r.status})")
            info = await r.json(content_type=None)
        try:
            project = info["projects"][0]
            self.ids = {"user_id": str(info["user"]["user_id"]), "filial_id": str(project["filials"][0][0]),
                        "project_code": str(project["code"])}
        except (KeyError, IndexError, TypeError) as e:
            raise CrmUnavailable("CRM вернула неожиданный ответ о сессии") from e

    async def _table(self, flt: list) -> list[dict[str, str]]:
        body = {"p": {"column": COLUMNS, "filter": flt, "sort": [], "offset": 0, "limit": 5}, "d": {}}
        for attempt in (1, 2):
            if self.ids is None:
                await self._sign_in()
            headers = {**self.ids, "lang_code": "ru"}
            async with self.http.post(self.base + "b/ap/stock_list&table", json=body, headers=headers) as r:
                if r.status == 401 and attempt == 1:  # сессия истекла — входим заново
                    self.ids = None
                    continue
                if r.status != 200:
                    raise CrmUnavailable(f"таблица остатков: HTTP {r.status}")
                data = await r.json(content_type=None)
            return [dict(zip(COLUMNS, row)) for row in data.get("data", [])]
        raise CrmUnavailable("CRM не пускает после повторного входа")

    async def find_sold(self, vin: str) -> SoldCar | None:
        """Проданная машина (состояние «Архив») с этим VIN или None. CrmUnavailable — проверить не удалось."""
        if not self.configured:
            raise CrmUnavailable("CarSale CRM не настроена (CARSALE_CRM_LOGIN / CARSALE_CRM_PASSWORD в .env)")
        hit = self.cache.get(vin)
        if hit and time.monotonic() - hit[0] < (FOUND_TTL if hit[1] else MISSING_TTL):
            return hit[1]
        async with self.lock:  # один вход на всех, запросы по очереди — CRM не нагружаем
            try:
                rows = await self._table(["and", [["vin_code", "=", vin], ["state", "=", ARCHIVE]]])
            except CrmUnavailable:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                self.ids = None
                raise CrmUnavailable(f"нет связи с CarSale CRM: {e.__class__.__name__}") from e
        found = next((sold_car(r) for r in rows if r.get("vin_code") == vin and r.get("state") == ARCHIVE), None)
        self.cache[vin] = (time.monotonic(), found)
        if len(self.cache) > 5000:
            self.cache.clear()
        return found


_crm: CarsaleCRM | None = None


def crm() -> CarsaleCRM:
    """Один клиент на процесс. Логин отдельный (CARSALE_CRM_*) или тот же, что для app.carsale.uz (CARSALE_*)."""
    global _crm
    if _crm is None:
        _crm = CarsaleCRM(os.getenv("CARSALE_CRM_URL", "https://crm.carsale.uz").strip(),
                          (os.getenv("CARSALE_CRM_LOGIN") or os.getenv("CARSALE_LOGIN") or "").strip(),
                          os.getenv("CARSALE_CRM_PASSWORD") or os.getenv("CARSALE_PASSWORD") or "")
    return _crm


async def close_crm() -> None:
    """При остановке сервиса — закрыть соединение с CRM (если его открывали)."""
    if _crm is not None:
        await _crm.close()


def set_crm(client: CarsaleCRM | None) -> None:
    """Для тестов: подменить клиента."""
    global _crm
    _crm = client
