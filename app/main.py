"""Точка входа: python -m app.main"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from app.config import load_settings
from app.database.database import create_engine, create_session_factory
from app.handlers import admin, cart, catalog, orders, fallback, language, phone, profile, region, start
from app.middlewares.db import DbSessionMiddleware
from app.services.localization import i18n
from app.services.orders import set_timezone

logger = logging.getLogger("jac_parts_bot")


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # httpx/aiohttp не печатаем на DEBUG, чтобы токен из URL не попал в логи
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    set_timezone(settings.timezone)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp["settings"] = settings
    dp["session_factory"] = session_factory  # для импорта Excel (отдельная транзакция)

    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.include_router(admin.router)  # только для ADMIN_IDS
    dp.include_router(start.router)
    dp.include_router(language.router)
    dp.include_router(region.router)
    dp.include_router(profile.router)
    dp.include_router(catalog.router)
    dp.include_router(orders.router)  # до cart: перехватывает «Оформить заказ»
    dp.include_router(cart.router)
    dp.include_router(phone.router)  # ловит все остальные сообщения — после остальных
    dp.include_router(fallback.router)  # всегда последним

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Update handling failed", exc_info=event.exception)
        update = event.update
        target = update.message or (update.callback_query and update.callback_query.message)
        if target is not None:
            try:
                await target.answer(i18n.t(None, "error_generic"))
            except Exception:
                pass
        return True

    me = await bot.get_me()
    logger.info("Bot @%s started (long polling). Admins: %d", me.username, len(settings.admin_ids))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
