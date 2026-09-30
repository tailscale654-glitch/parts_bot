"""python -m app.sync [--once] — сервис синхронизации остатков с CarSale."""
import asyncio
import logging
import sys

from aiogram import Bot

from app.config import load_settings
from app.database.database import create_engine, create_session_factory
from app.services.orders import set_timezone
from app.sync.runner import SyncConfig, loop


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    set_timezone(settings.timezone)
    cfg = SyncConfig.from_env()
    engine = create_engine(settings.database_url)
    bot = Bot(token=settings.bot_token)  # только чтобы написать администраторам
    logging.getLogger("app.sync").info("CarSale sync: каждые %s мин., логин %s", cfg.every_minutes or "— (по кнопке)",
                                       cfg.login or "не задан")
    try:
        await loop(create_session_factory(engine), cfg, bot, settings, once="--once" in sys.argv)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
