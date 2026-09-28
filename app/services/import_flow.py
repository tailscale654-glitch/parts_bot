"""Общее для загрузки Excel из бота (/admin) и из веб-панели: справочные данные из базы,
пробный прогон, тексты предпросмотра и ошибок."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Dealer, PartTranslation
from app.database.repositories.regions import RegionRepository
from app.services.dealers import DirectoryStats, apply_directory
from app.services.excel_import import ImportError_, ImportStats, apply_import, validate_any
from app.services.localization import i18n

MAX_ERRORS_SHOWN = 20


async def known_dealers(session: AsyncSession) -> dict[str, int]:
    """Дилеры из справочника: ключ названия → регион."""
    rows = await session.execute(select(Dealer.name_key, Dealer.region_id).where(Dealer.in_directory.is_(True)))
    return dict(rows.all())


async def known_translations(session: AsyncSession) -> dict[str, dict[str, str | None]]:
    """Переводы названий, заданные в веб-панели: ключ → {"ru", "uz"}."""
    rows = await session.scalars(select(PartTranslation))
    return {t.key: {"ru": t.name_ru, "uz": t.name_uz} for t in rows}


async def validate_path(session: AsyncSession, path: Path):
    """→ (строки, ошибки, предупреждения, формат) с учётом справочника дилеров и переводов из панели."""
    regions = await RegionRepository(session).list_active()
    return validate_any(path, regions, await known_dealers(session), await known_translations(session))


async def run_import(db: AsyncSession, rows, fmt: str) -> ImportStats | DirectoryStats:
    return await (apply_directory(db, rows) if fmt == "directory" else apply_import(db, rows))


async def dry_run(session_factory: async_sessionmaker, rows, fmt: str) -> ImportStats | DirectoryStats:
    """Пробный прогон: считаем, что изменится, и откатываем — база не меняется."""
    async with session_factory() as dry:
        try:
            return await run_import(dry, rows, fmt)
        finally:
            await dry.rollback()


def stats_text(key: str, stats, fmt: str, lang: str) -> str:
    return i18n.t(lang, f"directory_{key}" if fmt == "directory" else f"import_{key}", **vars(stats))


def issue_lines(issues: list[ImportError_], lang: str, limit: int = MAX_ERRORS_SHOWN) -> list[str]:
    lines = []
    for e in issues[:limit]:
        text = i18n.t(lang, e.key, **e.params)
        lines.append(i18n.t(lang, "import_row", row=e.row, error=text) if e.row else text)
    if len(issues) > limit:
        lines.append(i18n.t(lang, "import_more_errors", n=len(issues) - limit))
    return lines


def errors_text(errors: list[ImportError_], lang: str) -> str:
    lines = [i18n.t(lang, "import_failed_title"), ""]
    for e in errors[:MAX_ERRORS_SHOWN]:
        text = i18n.t(lang, e.key, **e.params)
        lines.append(i18n.t(lang, "import_row", row=e.row, error=text) if e.row else f"• {text}")
    if len(errors) > MAX_ERRORS_SHOWN:
        lines.append(i18n.t(lang, "import_more_errors", n=len(errors) - MAX_ERRORS_SHOWN))
    lines += ["", i18n.t(lang, "import_fix_hint")]
    return "\n".join(lines)[:4000]  # лимит Telegram — 4096 символов


def preview_text(stats, warnings: list[ImportError_], fmt: str, lang: str, question: bool = True) -> str:
    lines = [i18n.t(lang, f"import_format_{fmt}"), "", stats_text("preview", stats, fmt, lang)]
    if warnings:
        lines += ["", i18n.t(lang, "import_warnings_title"), *issue_lines(warnings, lang)]
    if question:
        lines += ["", i18n.t(lang, "import_confirm_question")]
    return "\n".join(lines)[:4000]
