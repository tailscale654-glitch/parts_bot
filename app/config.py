"""Настройки бота. Все секреты читаются только из .env / переменных окружения."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _build_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    user = os.getenv("POSTGRES_USER", "jac_bot")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "jac_parts")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)  # repr=False — токен не попадёт в логи
    admin_ids: set[int]
    database_url: str = field(repr=False)
    default_language: str = "ru"
    log_level: str = "INFO"


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Заполните файл .env (см. .env.example).")
    return Settings(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        database_url=_build_database_url(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
