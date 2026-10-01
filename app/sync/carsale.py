"""Чтение остатков у дилеров из CarSale (app.carsale.uz) через обычный браузер (Playwright).

У CarSale нет API, поэтому сервис делает то же, что человек:
  1. открывает страницу входа, вписывает логин и пароль из .env, нажимает «Войти»;
  2. открывает «Запчасти → Список запчастей»;
  3. ставит фильтр «Статус: У дилера» и запоминает общий итог «Кол-во у дилера»;
  4. по очереди выбирает каждого дилера (фильтр «Дилер»), показывает 1000 строк на странице
     и переписывает таблицу.

Почему по дилерам, а не листая страницы: в CarSale постраничный просмотр работает с ошибкой
(при 500/1000 строк вторая страница начинается с 51-й записи, а при одинаковом времени обновления
строки на соседних страницах повторяются и теряются). У одного дилера строк меньше 1000 — всё
помещается на первую страницу.

Проверки (если хоть одна не прошла — ничего не меняем):
  • сумма «Кол-во» строк дилера = итогу «Кол-во у дилера», который показывает CarSale;
  • сумма по всем дилерам = общему итогу при фильтре «У дилера».
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

logger = logging.getLogger(__name__)

# Колонки таблицы CarSale (как в их выгрузке «Список запчастей»), по порядку после служебной первой ячейки
COLUMNS = ["№", "Кол-во", "Код запчасти", "Название запчасти", "Статус", "Тип запчасти", "Автомобильная марка",
           "Цена продажи", "Цена реализации", "Склад", "Ячейка", "Инвойс", "На Дилера", "Последнее перемещение",
           "Дата обновления"]
DEALER_STATUS = "У дилера"
ROWS_PER_PAGE = "1000"


class CarsaleError(Exception):
    """Понятная человеку причина, почему синхронизация не удалась."""


@dataclass
class DealerResult:
    name: str
    rows: int
    pieces: int  # сумма «Кол-во» в строках
    kpi: int | None  # «Кол-во у дилера» по данным CarSale


@dataclass
class Snapshot:
    rows: list[list[str]] = field(default_factory=list)  # строки таблицы в порядке COLUMNS
    dealers: list[DealerResult] = field(default_factory=list)
    total_kpi: int | None = None  # «Кол-во у дилера» при фильтре только по статусу

    @property
    def pieces(self) -> int:
        return sum(d.pieces for d in self.dealers)


# ---------- код, который выполняется внутри страницы CarSale ----------
# Общие помощники: поиск кнопок по тексту, групп фильтров по заголовку, чтение таблицы и итога.
JS_HELPERS = r"""
const sleep = ms => new Promise(r => setTimeout(r, ms));
const buttons = () => [...document.querySelectorAll('button')];
const byLabel = label => buttons().find(b => (b.getAttribute('aria-label') || b.title) === label);
const byText = (text, root = document) => [...root.querySelectorAll('button')].find(b => b.innerText.trim() === text);
const kpi = () => {
  const m = (document.querySelector('main')?.innerText || '').match(/КОЛ-ВО У ДИЛЕРА\s+([\d\s]+)/i);
  return m ? parseInt(m[1].replace(/\s/g, ''), 10) : null;
};
const readRows = () => [...document.querySelectorAll('main table tbody tr')]
  .map(tr => [...tr.children].map(td => td.innerText.trim()))
  .filter(cells => cells.length >= 16 && cells[3]);
const pieces = rows => rows.reduce((s, c) => s + (parseInt(c[2], 10) || 0), 0);
const visible = el => !!(el && el.getClientRects().length);
const panel = () => {
  let el = buttons().find(b => visible(b) && b.innerText.includes('Применить'));
  while (el && !/ДИЛЕР/.test(el.innerText || '')) el = el.parentElement;
  return el;
};
const group = title => {  // блок фильтра («СТАТУС», «ДИЛЕР») внутри панели фильтров
  const root = panel();
  if (!root) return null;
  const head = [...root.querySelectorAll('*')].filter(e => e.children.length === 0 && e.innerText?.trim() === title).pop();
  let box = head?.parentElement;
  while (box && box.querySelectorAll('button').length < 2) box = box.parentElement;
  return box;
};
const openPanel = async () => {
  if (!panel()) {  // кнопка-иконка (узкий экран) или «Фильтры» (широкий)
    const opener = byLabel('Открыть панель фильтров') || buttons().find(b => b.innerText.trim().startsWith('Фильтры'));
    opener?.click(); await sleep(1200);
  }
  if (!panel()) throw new Error('Не открылась панель фильтров');
  if (!group('ДИЛЕР')) {  // открыт другой раздел панели («Прочее») — переключаемся на «Запчасти»
    buttons().find(b => b.innerText.trim().startsWith('Запчасти') && panel()?.contains(b))?.click();
    await sleep(500);
  }
};
const activeCount = () => {  // «2 активных» в шапке панели фильтров
  const m = (panel()?.innerText || '').match(/(\d+)\s+активн/);
  return m ? parseInt(m[1], 10) : 0;
};
const resetFilters = async () => {  // «Снять все (N)» в каждой группе фильтров
  for (let i = 0; i < 15 && activeCount() > 0; i++) {
    const clear = [...(panel()?.querySelectorAll('button') || [])]
      .find(b => visible(b) && /^Снять все/.test(b.innerText.trim()) && !/\(0\)/.test(b.innerText));
    if (!clear) break;
    clear.click(); await sleep(500);
  }
  if (activeCount() > 0) throw new Error('Не удалось снять фильтры');
};
const chip = (title, text) => {
  const box = group(title);
  if (!box) throw new Error(`Нет группы фильтров «${title}»`);
  const b = [...box.querySelectorAll('button')].find(x => x.innerText.replace('×', '').trim() === text);
  if (!b) throw new Error(`Нет кнопки «${text}» в фильтре «${title}»`);
  const before = activeCount();
  b.click();
  return before;
};
const chipOn = async (title, text) => {  // включить и убедиться, что фильтр стал активным
  const before = chip(title, text);
  for (let i = 0; i < 10 && activeCount() <= before; i++) await sleep(200);
  if (activeCount() <= before) throw new Error(`Фильтр «${text}» не включился`);
};
const applyAndWait = async (kpiOnly = false) => {
  buttons().find(b => visible(b) && b.innerText.includes('Применить'))?.click();
  await sleep(1500);
  const size = [...document.querySelectorAll('main button')].find(b => b.innerText.trim() === '%ROWS%');
  size?.click(); await sleep(1500);
  const first = byLabel('Первая страница');
  if (first && !first.disabled) { first.click(); await sleep(1500); }
  // ждём, пока таблица и итог «Кол-во у дилера» перестанут меняться и сойдутся
  let last = null;
  for (let i = 0; i < 60; i++) {
    const rows = readRows(), k = kpi(), s = pieces(rows);
    const sig = `${rows.length}|${s}|${k}`;
    if (sig === last && k !== null && (s === k || kpiOnly)) return {rows, kpi: k, sum: s, ok: s === k};
    last = sig; await sleep(700);
  }
  const rows = readRows();
  return {rows, kpi: kpi(), sum: pieces(rows), ok: false};
};
""".replace("%ROWS%", ROWS_PER_PAGE)

JS_DEALERS = JS_HELPERS + r"""
return (async () => {
  await openPanel();
  await resetFilters();
  await chipOn('СТАТУС', '%STATUS%');
  const box = group('ДИЛЕР');
  const names = box ? [...box.querySelectorAll('button')].map(b => b.innerText.replace('×', '').trim())
    .filter(t => t && !/^(Сбросить|Снять все)/.test(t)) : [];
  const res = await applyAndWait(true);
  return {names, total: res.kpi, shown: res.rows.length};
})();
""".replace("%STATUS%", DEALER_STATUS)

JS_DEALER = JS_HELPERS + r"""
return (async (dealer) => {
  await openPanel();
  await resetFilters();
  await chipOn('СТАТУС', '%STATUS%');
  await chipOn('ДИЛЕР', dealer);
  const res = await applyAndWait();
  const more = byLabel('Следующая страница');
  return {...res, hasNext: !!(more && !more.disabled)};
})(DEALER);
""".replace("%STATUS%", DEALER_STATUS)


def _js(body: str, **args) -> str:
    """Оборачиваем в функцию для page.evaluate; аргументы подставляем как JSON."""
    import json
    for name, value in args.items():
        body = body.replace(name, json.dumps(value, ensure_ascii=False))
    return "() => {" + body + "}"


# ---------- сам браузер ----------

async def sign_in(page, base_url: str, login: str, password: str) -> None:
    """Страница входа CarSale: логин, пароль, Enter (или кнопка «Войти в систему»)."""
    from playwright.async_api import TimeoutError as PwTimeout

    await page.goto(f"{base_url}/auth", wait_until="domcontentloaded")
    try:
        await page.get_by_placeholder("Введите логин").fill(login)
        await page.get_by_placeholder("Введите пароль").fill(password)
    except PwTimeout as e:
        raise CarsaleError("Не нашёл поля логина и пароля на странице входа CarSale") from e
    await page.get_by_placeholder("Введите пароль").press("Enter")
    try:
        await page.wait_for_url(lambda url: "/auth" not in url, timeout=30_000)
    except PwTimeout:
        button = page.get_by_text("Войти в систему", exact=True)
        if await button.count():
            await button.first.click()
        try:
            await page.wait_for_url(lambda url: "/auth" not in url, timeout=30_000)
        except PwTimeout as e:
            raise CarsaleError("CarSale не пустил: проверьте CARSALE_LOGIN и CARSALE_PASSWORD") from e
    logger.info("CarSale: вход выполнен")


async def fetch_snapshot(login: str, password: str, base_url: str = "https://app.carsale.uz",
                         skip_dealers: set[str] | None = None, headless: bool = True) -> Snapshot:
    """Войти в CarSale и прочитать остатки всех дилеров. Бросает CarsaleError с понятной причиной."""
    from playwright.async_api import TimeoutError as PwTimeout
    from playwright.async_api import async_playwright

    if not login or not password:
        raise CarsaleError("Не заданы CARSALE_LOGIN и CARSALE_PASSWORD в .env")
    skip = {s.strip().lower() for s in (skip_dealers or set()) if s.strip()}
    base_url = base_url.rstrip("/")
    snap = Snapshot()
    checked = 0  # штук по всем дилерам, включая пропущенные
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, executable_path=os.getenv("CHROMIUM_PATH") or None)
        try:
            page = await (await browser.new_context(locale="ru-RU", viewport={"width": 1600, "height": 1000})).new_page()
            page.set_default_timeout(60_000)

            await sign_in(page, base_url, login, password)  # 1. вход

            # 2. список запчастей
            await page.goto(f"{base_url}/spare-parts/parts-list", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector("main table tbody tr", timeout=60_000)
            except PwTimeout as e:
                raise CarsaleError("Не загрузилась страница «Список запчастей»") from e

            # 3. фильтр «У дилера»: общий итог и список дилеров
            info = await page.evaluate(_js(JS_DEALERS))
            snap.total_kpi = info.get("total")
            names = info.get("names", [])
            if not names:
                raise CarsaleError("В фильтре «Дилер» не нашлось ни одного дилера — возможно, CarSale изменил страницу")
            logger.info("CarSale: %d дилеров, всего у дилеров %s шт.", len(names), snap.total_kpi)

            # 4. по каждому дилеру
            for name in names:
                res = await page.evaluate(_js(JS_DEALER, DEALER=name))
                if res.get("hasNext"):
                    raise CarsaleError(f"У дилера «{name}» больше {ROWS_PER_PAGE} строк — нужна доработка")
                if not res.get("ok"):
                    raise CarsaleError(f"Дилер «{name}»: в таблице {res.get('sum')} шт., а CarSale показывает "
                                       f"{res.get('kpi')} шт. Данные не сошлись — ничего не меняю.")
                logger.info("CarSale: %s — %d строк, %d шт.", name, len(res["rows"]), res["sum"])
                checked += res["sum"]
                if name.lower() in skip:  # тестовые дилеры: считаем для проверки, но в бот не берём
                    continue
                snap.dealers.append(DealerResult(name, len(res["rows"]), res["sum"], res["kpi"]))
                snap.rows.extend(cells[1:16] for cells in res["rows"])
        finally:
            await browser.close()

    if snap.total_kpi is not None and checked != snap.total_kpi:
        raise CarsaleError(f"Сумма по дилерам ({checked} шт.) не равна общему итогу CarSale "
                           f"({snap.total_kpi} шт.) — ничего не меняю.")
    return snap


def write_xlsx(snap: Snapshot, path: Path) -> Path:
    """Сохранить в том же виде, что и выгрузка CarSale «Список запчастей» — дальше работает обычный импорт."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Запчасти"
    ws.append(["Список запчастей"])
    ws.append([f"Синхронизация с CarSale {datetime.now():%d.%m.%Y %H:%M} · {len(snap.rows)} записей"])
    ws.append([])
    ws.append(COLUMNS)
    for cells in snap.rows:
        ws.append(list(cells[:len(COLUMNS)]))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
