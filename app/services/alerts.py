"""Сообщения администраторам об ошибках в боте.
Одинаковая ошибка — не чаще одного раза в 10 минут, чтобы не засыпать сообщениями."""
import logging
import time
import traceback

from aiogram import Bot

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 600


class ErrorAlerts:
    def __init__(self, window: int = WINDOW_SECONDS):
        self.window = window
        self._last: dict[str, float] = {}

    @staticmethod
    def key(exc: BaseException) -> str:
        tb = traceback.extract_tb(exc.__traceback__)
        where = f"{tb[-1].filename.rsplit('/', 1)[-1]}:{tb[-1].lineno}" if tb else "?"
        return f"{type(exc).__name__}@{where}"

    def should_send(self, exc: BaseException, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        k = self.key(exc)
        if now - self._last.get(k, -1e9) < self.window:
            return False
        self._last[k] = now
        return True

    @staticmethod
    def text(exc: BaseException, update_id: int | None) -> str:
        tb = traceback.extract_tb(exc.__traceback__)
        own = [f for f in tb if "/app/" in f.filename] or tb  # показываем строки нашего кода
        where = "\n".join(f"  {f.filename.rsplit('/app/', 1)[-1]}:{f.lineno} {f.name}" for f in own[-3:])
        message = str(exc)[:300]
        return (f"⚠️ Ошибка в боте\n\n{type(exc).__name__}: {message}\n\n{where}\n\n"
                f"update_id: {update_id}\nПодробно: docker compose logs --tail 100 bot")

    async def notify(self, bot: Bot, admin_ids: set[int], exc: BaseException, update_id: int | None) -> None:
        if not admin_ids or not self.should_send(exc):
            return
        text = self.text(exc, update_id)
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:  # сообщение об ошибке не должно само ронять бота
                logger.warning("Cannot send error alert to %s: %s", admin_id, e)
