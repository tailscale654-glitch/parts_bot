"""Доступ к веб-панели из бота: /panel, новый пароль, приглашение сотрудника (t.me/бот?start=staff_…)."""
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import User
from app.database.repositories.staff import InviteError
from app.database.repositories.web_users import WebUserRepository
from app.services.localization import i18n
from app.services.notify import notify_admins_text, person_name
from app.services.roles import ROLES

router = Router(name="panel_access")


def _url(settings: Settings, lang) -> str:
    return settings.web_url or i18n.t(lang, "web_url_missing")


def _kb(lang, has_access: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=i18n.t(lang, "btn_web_new_password" if has_access else "btn_web_password"),
                                  callback_data="wp:new")]]
    if has_access:
        rows.append([InlineKeyboardButton(text=i18n.t(lang, "btn_web_disable"), callback_data="wp:off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _password_message(target: Message, lang, settings: Settings, login: str, password: str, role: str) -> None:
    await target.answer(
        i18n.t(lang, "web_password", url=_url(settings, lang), login=login, password=password, role=ROLES[role]),
        parse_mode="HTML",
    )


async def _info(user: User, session: AsyncSession, settings: Settings) -> tuple[str, InlineKeyboardMarkup | None]:
    lang = user.language
    web = await WebUserRepository(session).for_user(user)
    is_admin = user.telegram_id in settings.admin_ids
    if web is not None and web.active:
        return i18n.t(lang, "web_info", url=_url(settings, lang), login=web.login, role=ROLES[web.role]), _kb(lang, True)
    if is_admin:  # администратор из .env может выдать доступ сам себе
        return i18n.t(lang, "web_no_access", url=_url(settings, lang)), _kb(lang, False)
    return i18n.t(lang, "web_ask_admin"), None


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^staff_[\w-]+$")))
async def accept_invite(message: Message, command: CommandObject, user: User, session: AsyncSession,
                        bot: Bot, settings: Settings) -> None:
    lang = user.language
    try:
        login, password, role = await WebUserRepository(session).accept_invite(command.args.removeprefix("staff_"), user)
    except InviteError as e:
        await message.answer(i18n.t(lang, f"invite_{e.reason}"))
        return
    await message.answer(i18n.t(lang, "panel_invite_ok"))
    await _password_message(message, lang, settings, login, password, role)
    await notify_admins_text(bot, settings, session, "admin_panel_joined", name=person_name(user), role=ROLES[role])


@router.message(Command("panel"))
async def cmd_panel(message: Message, user: User, session: AsyncSession, settings: Settings) -> None:
    text, kb = await _info(user, session, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.in_({"wp:info", "wp:new", "wp:off"}))
async def panel_buttons(callback: CallbackQuery, user: User, session: AsyncSession, settings: Settings) -> None:
    lang = user.language
    repo = WebUserRepository(session)
    web = await repo.for_user(user)
    is_admin = user.telegram_id in settings.admin_ids
    if callback.data == "wp:new":
        if not (is_admin or (web is not None and web.active)):  # отключённый сотрудник пароль не получит
            await callback.answer(i18n.t(lang, "web_ask_admin"), show_alert=True)
            return
        login, password = await repo.issue_password(user, role="admin" if is_admin else None)
        await callback.answer()
        await _password_message(callback.message, lang, settings, login, password, "admin" if is_admin else web.role)
        return
    if callback.data == "wp:off" and web is not None:
        await repo.disable(user)
        await callback.answer(i18n.t(lang, "web_disabled"), show_alert=True)
    else:
        await callback.answer()
    text, kb = await _info(user, session, settings)
    await callback.message.edit_text(text, reply_markup=kb)
