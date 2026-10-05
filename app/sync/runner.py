"""Синхронизация остатков с CarSale: расписание, проверки безопасности, запись в базу, уведомления.

Запуск (docker-compose, сервис sync):  python -m app.sync
Разовый запуск для проверки:           python -m app.sync --once
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiogram.types import BufferedInputFile

from app.database.models import BotSetting, CarsaleOp, Order, Part, SyncRun
from app.database.repositories.orders import carsale_mode
from app.services import import_flow
from app.services.notify import notify_admins_text, send
from app.services.part_catalog import SYNC_REQUEST_KEY as REQUEST_KEY  # флаг «Синхронизировать сейчас»
from app.sync.carsale import CarsaleError, Snapshot, fetch_snapshot, write_xlsx
from app.sync.carsale_orders import AfterSaveError, SaleLine, SaleRequest, SaleResult, submit_sale

logger = logging.getLogger(__name__)
LANG = "ru"


@dataclass
class SyncConfig:
    login: str = ""
    password: str = ""
    base_url: str = "https://app.carsale.uz"
    every_minutes: int = 30  # 0 — только по кнопке в панели
    skip_dealers: frozenset[str] = frozenset({"test diler"})
    max_hidden_share: float = 0.3  # не скрывать за раз больше 30% деталей — скорее всего, CarSale отдал не всё

    @classmethod
    def from_env(cls) -> "SyncConfig":
        skip = os.getenv("CARSALE_SKIP_DEALERS", "test diler")
        return cls(
            login=os.getenv("CARSALE_LOGIN", ""),
            password=os.getenv("CARSALE_PASSWORD", ""),
            base_url=os.getenv("CARSALE_URL", "https://app.carsale.uz"),
            every_minutes=int(os.getenv("CARSALE_SYNC_MINUTES", "30") or 0),
            skip_dealers=frozenset(s.strip() for s in skip.split(",") if s.strip()),
            max_hidden_share=float(os.getenv("CARSALE_MAX_HIDDEN_SHARE", "0.3")),
        )


Fetcher = Callable[[SyncConfig], Awaitable[Snapshot]]


async def default_fetcher(cfg: SyncConfig) -> Snapshot:
    return await fetch_snapshot(cfg.login, cfg.password, cfg.base_url, set(cfg.skip_dealers))


async def run_sync(session_factory: async_sessionmaker, cfg: SyncConfig, trigger: str = "schedule",
                   fetcher: Fetcher = default_fetcher) -> SyncRun:
    """Одна синхронизация. Всё или ничего: если что-то не сошлось — база не меняется."""
    async with session_factory() as session:
        run = SyncRun(trigger=trigger, status="running")
        session.add(run)
        await session.commit()
        run_id = run.id

    status, summary, error = "failed", "", ""
    untranslated: list[str] = []
    snap: Snapshot | None = None
    path = Path(tempfile.gettempdir()) / f"carsale_{run_id}.xlsx"
    try:
        snap = await fetcher(cfg)
        write_xlsx(snap, path)
        async with session_factory() as session:
            rows, errors, warnings, fmt = await import_flow.validate_path(session, path)
            if errors:
                raise CarsaleError(import_flow.errors_text(errors, LANG))
            preview = await import_flow.dry_run(session_factory, rows, fmt)
            active = await session.scalar(select(func.count(Part.id)).where(Part.active.is_(True))) or 0
            if active >= 20 and preview.hidden > active * cfg.max_hidden_share:
                raise CarsaleError(
                    f"Синхронизация скрыла бы {preview.hidden} из {active} деталей — это слишком много, "
                    "скорее всего CarSale отдал не все данные. Ничего не меняю. "
                    "Если так и должно быть — загрузите выгрузку вручную в панели.")
        async with session_factory() as db:
            try:
                stats = await import_flow.run_import(db, rows, fmt)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        status = "ok"
        untranslated = sorted({r.part_name["en"] for r in rows if r.part_name["ru"] == r.part_name["en"]
                               and not r.part_name.get("uz")})
        summary = import_flow.stats_text("applied", stats, fmt, LANG)
        if warnings:
            summary += "\n\n" + "\n".join(import_flow.issue_lines(warnings, LANG, limit=10))
        logger.info("CarSale sync %s ok: %s", run_id, stats)
    except CarsaleError as e:
        error = str(e)
        logger.warning("CarSale sync %s failed: %s", run_id, e)
    except Exception as e:  # неожиданная ошибка — в журнал с подробностями
        error = f"{type(e).__name__}: {e}"[:2000]
        logger.exception("CarSale sync %s crashed", run_id)
    finally:
        path.unlink(missing_ok=True)

    async with session_factory() as session:
        run = await session.get(SyncRun, run_id)
        run.status, run.summary, run.error = status, summary, error
        run.finished_at = datetime.now(timezone.utc)
        run.untranslated = untranslated if status == "ok" else []
        if snap is not None:
            run.rows, run.dealers, run.pieces = len(snap.rows), len(snap.dealers), snap.pieces
        await session.commit()
        return run


async def previous_status(session: AsyncSession, before_id: int) -> str | None:
    return await session.scalar(select(SyncRun.status).where(SyncRun.id < before_id, SyncRun.status != "running")
                                .order_by(SyncRun.id.desc()).limit(1))


UNTRANSLATED_KEY = "untranslated_notified"  # названия без перевода, о которых уже сообщили


async def new_untranslated(session_factory: async_sessionmaker, names: list[str]) -> list[str]:
    """Названия без перевода, о которых администраторам ещё не сообщали (чтобы не слать каждые 30 минут)."""
    async with session_factory() as session:
        flag = await session.get(BotSetting, UNTRANSLATED_KEY)
        seen = set(filter(None, (flag.value if flag else "").split("\n")))
        fresh = [n for n in names if n not in seen]
        value = "\n".join(sorted(set(names)))  # переведённые сами уходят из списка
        if flag is None:
            session.add(BotSetting(key=UNTRANSLATED_KEY, value=value))
        else:
            flag.value = value
        await session.commit()
        return fresh


async def notify(bot: Bot | None, session_factory: async_sessionmaker, settings, run: SyncRun) -> None:
    """Администраторам — только при смене состояния (сломалось / починилось) и при ручном запуске.
    Плюс: в CarSale появились детали с названием без перевода — сразу, один раз на каждое название."""
    fresh = await new_untranslated(session_factory, run.untranslated) if run.status == "ok" else []
    if bot is None:
        return
    if fresh:
        link = f"\n\nПеревести: {settings.web_url.rstrip('/')}/catalog?show=untranslated" if settings.web_url else ""
        text = (f"🈯 Новые детали без перевода: {len(fresh)}. Покупатели видят их по-английски.\n\n"
                + "\n".join(f"• {n}" for n in fresh[:30]) + ("\n…" if len(fresh) > 30 else "")
                + (link or "\n\nПеревести: веб-панель → Каталог → «Без перевода»."))
        for admin_id in settings.admin_ids:
            await send(bot, admin_id, text[:4000])
    async with session_factory() as session:
        before = await previous_status(session, run.id)
        if run.status == "failed" and (before != "failed" or run.trigger == "manual"):
            await notify_admins_text(bot, settings, session, "sync_failed", error=run.error[:1500])
        elif run.status == "ok" and (before == "failed" or run.trigger == "manual"):
            for admin_id in settings.admin_ids:
                await send(bot, admin_id, f"✅ Синхронизация с CarSale: {run.rows} строк, {run.dealers} дилеров, "
                                          f"{run.pieces} шт.\n\n{run.summary}"[:4000])


# ---------- продажи бота → CarSale ----------

SaleSubmitter = Callable[[SaleRequest, SyncConfig, bool], Awaitable[SaleResult]]


async def default_submitter(req: SaleRequest, cfg: SyncConfig, save: bool) -> SaleResult:
    return await submit_sale(req, cfg.login, cfg.password, cfg.base_url, save=save)


def sale_request(order: Order) -> SaleRequest:
    from app.services.notify import person_name

    lines: dict[str, SaleLine] = {}
    for item in order.items:
        line = lines.setdefault(item.part_number, SaleLine(item.part_number, item.name_en or item.name_ru, 0))
        line.quantity += item.quantity
    phone = "".join(ch for ch in (order.user.phone or "") if ch.isdigit())
    return SaleRequest(order_id=order.id, dealer_name=order.dealer.name, dealer_key=order.dealer.name_key,
                       client_name=person_name(order.user), client_phone=f"+{phone}" if phone else "",
                       lines=list(lines.values()))


async def process_sales(session_factory: async_sessionmaker, cfg: SyncConfig, bot: Bot | None, settings,
                        submitter: SaleSubmitter = default_submitter, limit: int = 5) -> int:
    """Обработать очередь: заказы, выданные клиенту, записать в CarSale. → сколько обработано."""
    mode = carsale_mode()
    if mode == "off" or not cfg.login or not cfg.password:
        return 0
    async with session_factory() as session:
        ids = list(await session.scalars(select(CarsaleOp.id).where(CarsaleOp.status == "queued")
                                         .order_by(CarsaleOp.id).limit(limit)))
    for op_id in ids:
        async with session_factory() as session:
            op = await session.get(CarsaleOp, op_id)
            if op is None or op.status != "queued":
                continue
            op.status, op.attempts = "running", op.attempts + 1
            await session.commit()
            req = sale_request(op.order)
        status, shot = "failed", b""
        try:
            result = await submitter(req, cfg, mode == "on")
            status = "done" if result.saved else "dry"
            message, shot = result.message, result.screenshot
        except AfterSaveError as e:
            status, message = "unknown", str(e)
        except CarsaleError as e:
            message, shot = str(e), getattr(e, "screenshot", b"")
        except Exception as e:
            message = f"{type(e).__name__}: {e}"[:1500]
            logger.exception("CarSale sale for order %s crashed", req.order_id)
        async with session_factory() as session:
            op = await session.get(CarsaleOp, op_id)
            op.status, op.message = status, message[:2000]
            await session.commit()
        logger.info("CarSale sale order %s: %s — %s", req.order_id, status, message)
        await notify_sale(bot, settings, req, status, message, shot)
    return len(ids)


async def notify_sale(bot: Bot | None, settings, req: SaleRequest, status: str, message: str, shot: bytes) -> None:
    if bot is None or settings is None or status == "done":
        return
    head = {"dry": "🧪 CarSale, пробный режим", "failed": "⚠️ CarSale: заказ не записан",
            "unknown": "❓ CarSale: проверьте вручную"}[status]
    text = f"{head} — заказ №{req.order_id}\n\n{message}"[:1000]
    for admin_id in settings.admin_ids:
        try:
            if shot:
                await bot.send_photo(admin_id, BufferedInputFile(shot, f"carsale_{req.order_id}.png"), caption=text)
            else:
                await send(bot, admin_id, text)
        except Exception as e:  # уведомление не должно ломать очередь
            logger.warning("Cannot notify %s about CarSale sale: %s", admin_id, e)


async def take_request(session_factory: async_sessionmaker) -> bool:
    """Нажали ли в панели «Синхронизировать сейчас» (флаг снимается)."""
    async with session_factory() as session:
        flag = await session.get(BotSetting, REQUEST_KEY)
        if flag is None or not flag.value:
            return False
        flag.value = ""
        await session.commit()
        return True


async def mark_stale(session_factory: async_sessionmaker) -> None:
    """Если сервис перезапустился посреди работы — синхронизацию отметить прерванной,
    а запись заказа — «unknown» (могла успеть сохраниться: человек проверит)."""
    async with session_factory() as session:
        for run in await session.scalars(select(SyncRun).where(SyncRun.status == "running")):
            run.status, run.error = "failed", "Прервано перезапуском сервиса"
            run.finished_at = datetime.now(timezone.utc)
        for op in (await session.scalars(select(CarsaleOp).where(CarsaleOp.status == "running"))).unique():
            op.status, op.message = "unknown", "Сервис перезапустился во время записи — проверьте заказ в CarSale"
        await session.commit()


async def loop(session_factory: async_sessionmaker, cfg: SyncConfig, bot: Bot | None, settings,
               fetcher: Fetcher = default_fetcher, poll_seconds: int = 20, once: bool = False,
               submitter: SaleSubmitter = default_submitter) -> None:
    for attempt in range(30):  # при первом запуске бот ещё может применять миграции
        try:
            await mark_stale(session_factory)
            break
        except Exception as e:
            logger.info("База ещё не готова (%s), жду…", type(e).__name__)
            await asyncio.sleep(10)
    if not cfg.login or not cfg.password:
        logger.warning("CARSALE_LOGIN / CARSALE_PASSWORD не заданы — синхронизация выключена")
        if once:
            return
    last_run = 0.0
    while True:
        try:
            await process_sales(session_factory, cfg, bot, settings, submitter)  # продажи — в первую очередь
        except Exception:
            logger.exception("CarSale sales queue error")
        try:
            manual = await take_request(session_factory)
            now = asyncio.get_running_loop().time()
            due = cfg.every_minutes > 0 and (last_run == 0.0 or now - last_run >= cfg.every_minutes * 60)
            if cfg.login and cfg.password and (manual or due or once):
                last_run = now
                run = await run_sync(session_factory, cfg, "manual" if manual else "schedule", fetcher)
                await notify(bot, session_factory, settings, run)
        except Exception:  # сервис не должен падать из-за одной неудачи
            logger.exception("CarSale sync loop error")
        if once:
            return
        await asyncio.sleep(poll_seconds)
