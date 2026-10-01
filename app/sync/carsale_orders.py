"""Запись продаж бота в CarSale: «Перемещение → Заказы запчастей → Оформить заказ».

Когда заказ в боте получает статус «Выдан», бот ставит его в очередь (таблица carsale_ops),
а сервис sync открывает CarSale и оформляет заказ: дилер, клиент (находит по телефону или
добавляет), запчасти с количеством, в «Примечании» — номер заказа бота.
В CarSale такой заказ сразу получает статус «Заказ реализован» — это и есть расход с дилера.

Режимы (CARSALE_ORDERS в .env):
  off — ничего не делать (по умолчанию);
  dry — заполнить форму, сделать скриншот, нажать «Отмена» (проверка без записи);
  on  — заполнить и нажать «Сохранить».

Защита от двойной записи: на каждый заказ — одна запись в carsale_ops (уникальный ключ).
Если что-то сломалось ПОСЛЕ нажатия «Сохранить», статус «unknown»: бот сам не повторяет,
администратор проверяет CarSale (по номеру заказа в «Примечании») и решает в панели.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field

from app.sync.carsale import CarsaleError, sign_in
from app.utils.names import dealer_key

logger = logging.getLogger(__name__)
NOTE_PREFIX = "JAC Parts Bot"


class AfterSaveError(CarsaleError):
    """Ошибка после нажатия «Сохранить» — заказ МОГ записаться. Не повторять автоматически."""


@dataclass
class SaleLine:
    part_number: str
    name: str
    quantity: int


@dataclass
class SaleRequest:
    order_id: int
    dealer_name: str
    dealer_key: str
    client_name: str
    client_phone: str  # +998XXXXXXXXX
    lines: list[SaleLine] = field(default_factory=list)

    @property
    def note(self) -> str:
        return f"{NOTE_PREFIX} · заказ №{self.order_id} · {self.client_name} {self.client_phone}".strip()


@dataclass
class SaleResult:
    saved: bool
    screenshot: bytes = b""
    message: str = ""


def phone_digits(phone: str | None) -> str:
    """Последние 9 цифр: «+998 90 123-45-67» → «901234567»."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-9:]


def pick_stock(entries: list[tuple[int, int]], quantity: int) -> int | None:
    """entries: (индекс в списке, остаток). Берём одну партию, где хватает на всё количество
    (из подходящих — с наибольшим остатком). Нет такой — None."""
    fitting = [e for e in entries if e[1] >= quantity]
    return max(fitting, key=lambda e: e[1])[0] if fitting else None


async def _wait(page, ms: int = 800) -> None:
    await page.wait_for_timeout(ms)


async def _click_visible(page, text: str) -> None:
    """Кнопка с этим текстом (может быть «+ Добавить …»); если не кнопка — любой видимый элемент."""
    pattern = re.compile(re.escape(text))
    button = page.get_by_role("button", name=pattern)
    if await button.count():
        await button.last.click()
        return
    await page.locator(f"*:visible:text-matches('{re.escape(text)}')").last.click()


async def _choose_dealer(page, req: SaleRequest) -> None:
    select = page.locator("select").filter(has=page.locator("option", has_text="Выберите дилера")).last
    labels = [t.strip() for t in await select.locator("option").all_inner_texts()]
    match = next((t for t in labels if dealer_key(t) == req.dealer_key), None)
    if match is None:
        raise CarsaleError(f"Дилера «{req.dealer_name}» нет в списке дилеров CarSale")
    await select.select_option(label=match)
    await _wait(page)


async def _choose_client(page, req: SaleRequest) -> str:
    """Найти клиента по имени и телефону или добавить нового. → «найден» / «добавлен»."""
    await _click_visible(page, "Выберите клиента")
    await _wait(page)
    search = page.get_by_placeholder(re.compile("Поиск по имени"))
    await search.fill(req.client_name[:40])
    await _wait(page, 1500)
    tail = phone_digits(req.client_phone)
    if tail:
        # строка клиента: «Имя / Физ. лицо · +998 90 123 45 67» — сравниваем по цифрам телефона
        candidates = page.locator("div, li, button").filter(has_text=re.compile("лицо"))
        count = await candidates.count()
        for i in range(count - 1, -1, -1):  # с конца — самые вложенные элементы
            item = candidates.nth(i)
            text = await item.inner_text()
            if len(text) < 200 and phone_digits(text) == tail and "Добавить клиента" not in text:
                await item.click()
                await _wait(page)
                return "найден"
    # не нашли — «Добавить клиента»: Физ. лицо, имя, телефон
    await _click_visible(page, "Добавить клиента")
    await _wait(page)
    form = page.locator("div").filter(has=page.get_by_text("Добавить клиента", exact=True)) \
        .filter(has=page.get_by_role("button", name="Добавить", exact=True)).last
    phys = form.get_by_text("Физ. лицо", exact=True)
    if await phys.count():
        await phys.first.click()
    inputs = form.locator("input:visible")
    if await inputs.count() < 2:
        raise CarsaleError("Не нашёл поля «Имя» и «Телефон» в форме «Добавить клиента»")
    await inputs.nth(0).fill(req.client_name[:100])
    await inputs.nth(1).fill(req.client_phone)
    await form.get_by_role("button", name="Добавить", exact=True).click()
    await _wait(page, 1500)
    if await page.get_by_text("Выберите клиента", exact=True).count():
        raise CarsaleError("CarSale не принял нового клиента (проверьте имя и телефон)")
    return "добавлен"


async def _add_part(page, req: SaleRequest, line: SaleLine) -> None:
    await _click_visible(page, "Добавить запчасть")
    await _wait(page)
    search = page.get_by_placeholder(re.compile("Поиск: код или название"))
    await search.fill(line.part_number)
    await _wait(page, 1800)
    # карточки в списке: «КОД / НАЗВАНИЕ / Остаток: 50 · 85 500 · ДИЛЕР»
    cards = page.locator("div, li, button").filter(has_text=re.compile(r"Остаток:\s*\d+")) \
        .filter(has_text=line.part_number)
    entries: list[tuple[int, int]] = []
    count = await cards.count()
    for i in range(count):
        text = await cards.nth(i).inner_text()
        if len(text) > 300 or text.count("Остаток") != 1:  # пропускаем внешние контейнеры
            continue
        first = text.strip().splitlines()[0].strip()
        if first.upper() != line.part_number.upper():
            continue
        info = next(ln for ln in text.splitlines() if "Остаток" in ln)  # «Остаток: 50 · 85 500 · ДИЛЕР»
        if dealer_key(info.rsplit("·", 1)[-1]) != req.dealer_key:
            continue
        stock = int(re.search(r"Остаток:\s*(\d+)", info).group(1))
        entries.append((i, stock))
    if not entries:
        raise CarsaleError(f"В CarSale у дилера нет запчасти {line.part_number}")
    index = pick_stock(entries, line.quantity)
    if index is None:
        best = max(s for _, s in entries)
        raise CarsaleError(f"{line.part_number}: нужно {line.quantity} шт., а в одной партии у дилера "
                           f"не больше {best} шт. Оформите этот заказ в CarSale вручную.")
    await cards.nth(index).click()
    await _wait(page)
    if line.quantity > 1:
        # строка добавленной запчасти: ищем поле количества рядом с кодом
        rows = page.locator("div, tr").filter(has_text=line.part_number).filter(has=page.locator("input"))
        if not await rows.count():
            raise CarsaleError(f"Не нашёл поле количества для {line.part_number}")
        qty = rows.last.locator("input").first
        await qty.fill(str(line.quantity))
        await _wait(page, 400)


async def submit_sale(req: SaleRequest, login: str, password: str, base_url: str = "https://app.carsale.uz",
                      save: bool = False, headless: bool = True) -> SaleResult:
    """Заполнить «Оформить заказ». save=False — только скриншот и «Отмена»."""
    from playwright.async_api import TimeoutError as PwTimeout
    from playwright.async_api import async_playwright

    if not login or not password:
        raise CarsaleError("Не заданы CARSALE_LOGIN и CARSALE_PASSWORD в .env")
    base_url = base_url.rstrip("/")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, executable_path=os.getenv("CHROMIUM_PATH") or None)
        try:
            page = await (await browser.new_context(locale="ru-RU", viewport={"width": 1500, "height": 1100})).new_page()
            page.set_default_timeout(30_000)
            await sign_in(page, base_url, login, password)
            step = "открыть «Перемещение»"
            try:
                await page.goto(f"{base_url}/spare-parts/movement", wait_until="domcontentloaded")
                await page.wait_for_load_state("networkidle")
                step = "вкладка «Заказы запчастей»"
                await _click_visible(page, "Заказы запчастей")
                await _wait(page, 2000)
                step = "кнопка «Оформить заказ»"
                await _click_visible(page, "Оформить заказ")
                await _wait(page, 1200)
                step = "выбор дилера"
                await _choose_dealer(page, req)
                step = "выбор клиента"
                client = await _choose_client(page, req)
                for line in req.lines:
                    step = f"запчасть {line.part_number}"
                    await _add_part(page, req, line)
                step = "примечание"
                await page.get_by_placeholder(re.compile("Комментарий к заказу")).last.fill(req.note)
                await _wait(page, 500)
            except (PwTimeout, CarsaleError) as e:
                error = CarsaleError(f"Шаг «{step}»: " + (str(e) if isinstance(e, CarsaleError) and not isinstance(
                    e, PwTimeout) else f"не нашёл нужный элемент ({str(e).splitlines()[0][:150]})"))
                try:
                    error.screenshot = await page.screenshot(full_page=False)
                except Exception:
                    pass
                raise error from e
            shot = await page.screenshot(full_page=False)
            summary = (f"дилер {req.dealer_name}, клиент {client}: {req.client_name} {req.client_phone}, "
                       + ", ".join(f"{ln.part_number} × {ln.quantity}" for ln in req.lines))
            if not save:
                await page.get_by_role("button", name="Отмена", exact=True).last.click()
                return SaleResult(saved=False, screenshot=shot, message="Пробный режим, не сохранено: " + summary)

            await page.get_by_role("button", name="Сохранить", exact=True).last.click()
            try:  # форма закрылась = CarSale принял заказ
                await page.get_by_role("button", name="Сохранить", exact=True).last.wait_for(state="hidden",
                                                                                             timeout=20_000)
            except PwTimeout as e:
                raise AfterSaveError("После «Сохранить» форма не закрылась — проверьте в CarSale, записался ли "
                                     f"заказ (Примечание: «{req.note}»)") from e
            await asyncio.sleep(1)
            return SaleResult(saved=True, screenshot=shot, message="Записано в CarSale: " + summary)
        finally:
            await browser.close()
