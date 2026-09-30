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

from app.database.models import BotSetting, Part, SyncRun
from app.services import import_flow
from app.services.notify import notify_admins_text, send
from app.sync.carsale import CarsaleError, Snapshot, fetch_snapshot, write_xlsx

logger = logging.getLogger(__name__)
REQUEST_KEY = "carsale_sync_request"  # веб-панель пишет сюда время нажатия «Синхронизировать сейчас»
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
        if snap is not None:
            run.rows, run.dealers, run.pieces = len(snap.rows), len(snap.dealers), snap.pieces
        await session.commit()
        return run


async def previous_status(session: AsyncSession, before_id: int) -> str | None:
    return await session.scalar(select(SyncRun.status).where(SyncRun.id < before_id, SyncRun.status != "running")
                                .order_by(SyncRun.id.desc()).limit(1))


async def notify(bot: Bot | None, session_factory: async_sessionmaker, settings, run: SyncRun) -> None:
    """Администраторам — только при смене состояния (сломалось / починилось) и при ручном запуске."""
    if bot is None:
        return
    async with session_factory() as session:
        before = await previous_status(session, run.id)
        if run.status == "failed" and (before != "failed" or run.trigger == "manual"):
            await notify_admins_text(bot, settings, session, "sync_failed", error=run.error[:1500])
        elif run.status == "ok" and (before == "failed" or run.trigger == "manual"):
            for admin_id in settings.admin_ids:
                await send(bot, admin_id, f"✅ Синхронизация с CarSale: {run.rows} строк, {run.dealers} дилеров, "
                                          f"{run.pieces} шт.\n\n{run.summary}"[:4000])


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
    """Если сервис перезапустился посреди синхронизации — отметить её как прерванную."""
    async with session_factory() as session:
        for run in await session.scalars(select(SyncRun).where(SyncRun.status == "running")):
            run.status, run.error = "failed", "Прервано перезапуском сервиса"
            run.finished_at = datetime.now(timezone.utc)
        await session.commit()


async def loop(session_factory: async_sessionmaker, cfg: SyncConfig, bot: Bot | None, settings,
               fetcher: Fetcher = default_fetcher, poll_seconds: int = 20, once: bool = False) -> None:
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
