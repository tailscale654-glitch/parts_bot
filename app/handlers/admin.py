"""Админ: /admin и загрузка Excel. Разделы панели — в admin_panel.py. Доступ только для ADMIN_IDS из .env."""
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Dealer, User
from app.database.repositories.regions import RegionRepository
from app.services.dealers import DirectoryStats, apply_directory
from app.services.excel_import import MAX_FILE_MB, ImportError_, ImportStats, apply_import, validate_any
from app.services.excel_template import build_template
from app.services.localization import i18n
from app.states.admin import ImportStates
from app.utils.filters import IsAdmin

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

IMPORT_DIR = Path(tempfile.gettempdir()) / "jac_imports"
MAX_ERRORS_SHOWN = 20


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=i18n.t(lang, "btn_apply"), callback_data="imp:apply"),
        InlineKeyboardButton(text=i18n.t(lang, "btn_cancel"), callback_data="imp:cancel"),
    ]])


def errors_text(errors: list[ImportError_], lang: str) -> str:
    lines = [i18n.t(lang, "import_failed_title"), ""]
    for e in errors[:MAX_ERRORS_SHOWN]:
        text = i18n.t(lang, e.key, **e.params)
        lines.append(i18n.t(lang, "import_row", row=e.row, error=text) if e.row else f"• {text}")
    if len(errors) > MAX_ERRORS_SHOWN:
        lines.append(i18n.t(lang, "import_more_errors", n=len(errors) - MAX_ERRORS_SHOWN))
    lines += ["", i18n.t(lang, "import_fix_hint")]
    return "\n".join(lines)[:4000]  # лимит Telegram — 4096 символов


async def known_dealers(session: AsyncSession) -> dict[str, int]:
    """Дилеры из справочника: ключ названия → регион."""
    rows = await session.execute(select(Dealer.name_key, Dealer.region_id).where(Dealer.in_directory.is_(True)))
    return dict(rows.all())


async def run_import(db: AsyncSession, rows, fmt: str) -> ImportStats | DirectoryStats:
    return await (apply_directory(db, rows) if fmt == "directory" else apply_import(db, rows))


def stats_text(key: str, stats, fmt: str, lang: str) -> str:
    return i18n.t(lang, f"directory_{key}" if fmt == "directory" else f"import_{key}", **vars(stats))


def preview_text(stats, warnings: list[ImportError_], fmt: str, lang: str) -> str:
    lines = [i18n.t(lang, f"import_format_{fmt}"), "", stats_text("preview", stats, fmt, lang)]
    if warnings:
        lines += ["", i18n.t(lang, "import_warnings_title")]
        for w in warnings[:MAX_ERRORS_SHOWN]:
            text = i18n.t(lang, w.key, **w.params)
            lines.append(i18n.t(lang, "import_row", row=w.row, error=text) if w.row else text)
    lines += ["", i18n.t(lang, "import_confirm_question")]
    return "\n".join(lines)[:4000]


def _remove(path: str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


@router.message(Command("admin"))
async def cmd_admin(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    from app.handlers.admin_panel import admin_menu_view  # меню собирается в admin_panel.py

    await state.clear()
    text, kb = await admin_menu_view(session, user.language)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:template")
async def send_template(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(build_template(), filename="jac_parts_template.xlsx"),
        caption=i18n.t(user.language, "template_caption"),
    )


@router.callback_query(F.data == "adm:upload")
async def ask_file(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(ImportStates.waiting_file)
    await callback.answer()
    await callback.message.answer(i18n.t(user.language, "import_ask_file"))


@router.message(StateFilter(ImportStates.waiting_file, ImportStates.confirm), F.document)
async def got_file(
    message: Message, bot: Bot, user: User, session: AsyncSession,
    session_factory: async_sessionmaker, state: FSMContext,
) -> None:
    lang = user.language
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".xlsx"):
        await message.answer(i18n.t(lang, "import_bad_extension"))
        return
    if (doc.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
        await message.answer(i18n.t(lang, "import_too_big", mb=MAX_FILE_MB))
        return

    _remove((await state.get_data()).get("path"))  # старый файл, если прислали новый
    status = await message.answer(i18n.t(lang, "import_checking"))
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = IMPORT_DIR / f"{message.from_user.id}.xlsx"
    await bot.download(doc, destination=path)

    regions = await RegionRepository(session).list_active()
    rows, errors, warnings, fmt = validate_any(path, regions, await known_dealers(session))
    if errors:
        _remove(str(path))
        await state.set_state(ImportStates.waiting_file)
        await status.edit_text(errors_text(errors, lang))
        return

    # Пробный прогон: считаем, что изменится, и откатываем — база не меняется
    async with session_factory() as dry:
        try:
            stats = await run_import(dry, rows, fmt)
        finally:
            await dry.rollback()

    await state.set_state(ImportStates.confirm)
    await state.update_data(path=str(path))
    await status.edit_text(preview_text(stats, warnings, fmt, lang), reply_markup=confirm_keyboard(lang))


@router.callback_query(StateFilter(ImportStates.confirm), F.data == "imp:apply")
async def apply(
    callback: CallbackQuery, user: User, session: AsyncSession,
    session_factory: async_sessionmaker, state: FSMContext,
) -> None:
    lang = user.language
    path = (await state.get_data()).get("path")
    await state.clear()
    await callback.answer()
    if not path or not Path(path).exists():
        await callback.message.edit_text(i18n.t(lang, "import_expired"))
        return

    regions = await RegionRepository(session).list_active()
    # проверяем ещё раз: регионы и справочник могли измениться
    rows, errors, _, fmt = validate_any(Path(path), regions, await known_dealers(session))
    if errors:
        _remove(path)
        await callback.message.edit_text(errors_text(errors, lang))
        return

    async with session_factory() as db:
        try:
            stats = await run_import(db, rows, fmt)
            await db.commit()  # всё или ничего: одна транзакция
        except Exception:
            await db.rollback()
            logger.exception("Excel import failed, rolled back")
            await callback.message.edit_text(i18n.t(lang, "import_db_error"))
            return
        finally:
            _remove(path)
    logger.info("Excel import by %s: %s", callback.from_user.id, stats)
    await callback.message.edit_text(stats_text("applied", stats, fmt, lang))


@router.callback_query(F.data.in_({"imp:apply", "imp:cancel"}))
async def cancel(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """«Отмена» — или «Применить» на старом сообщении, когда импорт уже неактуален."""
    _remove((await state.get_data()).get("path"))
    await state.clear()
    await callback.answer()
    key = "import_cancelled" if callback.data == "imp:cancel" else "import_expired"
    await callback.message.edit_text(i18n.t(user.language, key))
