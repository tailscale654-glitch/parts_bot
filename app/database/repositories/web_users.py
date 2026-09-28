"""Сотрудники веб-панели: логины, роли, приглашения."""
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelInvite, User, WebUser
from app.database.repositories.staff import INVITE_DAYS, InviteError, _aware
from app.services.roles import ROLES
from app.utils.passwords import generate_password, hash_password, verify_password


def make_login(user: User) -> str:
    """@username → username; иначе user<telegram_id>."""
    base = re.sub(r"[^a-z0-9_]", "", (user.username or "").lower())
    return base or f"user{user.telegram_id}"


class WebUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_user(self, user: User) -> WebUser | None:
        return await self.session.scalar(select(WebUser).where(WebUser.user_id == user.id))

    async def get(self, web_id: int) -> WebUser | None:
        return await self.session.get(WebUser, web_id)

    async def all(self) -> list[WebUser]:
        result = await self.session.scalars(select(WebUser).order_by(WebUser.active.desc(), WebUser.role, WebUser.id))
        return list(result.unique())

    async def issue_password(self, user: User, role: str | None = None) -> tuple[str, str]:
        """Создать доступ (с ролью) или выдать новый пароль. → (логин, пароль).
        Пароль нигде не хранится — только его хеш. Все прежние входы завершаются."""
        password = generate_password()
        web = await self.for_user(user)
        if web is None:
            login = make_login(user)
            if await self.session.scalar(select(WebUser.id).where(WebUser.login == login)):
                login = f"{login}{user.telegram_id % 10000}"
            web = WebUser(user_id=user.id, login=login, password_hash=hash_password(password),
                          role=role or "viewer", session_version=1)
            self.session.add(web)
        else:
            web.password_hash = hash_password(password)
            web.session_version += 1
            web.active = True
            if role:
                web.role = role
        await self.session.commit()
        return web.login, password

    async def set_role(self, web: WebUser, role: str) -> None:
        if role not in ROLES:
            raise ValueError(role)
        web.role = role
        web.session_version += 1  # права меняются сразу — нужно войти заново
        await self.session.commit()

    async def set_active(self, web: WebUser, active: bool) -> None:
        web.active = active
        web.session_version += 1
        await self.session.commit()

    async def disable(self, user: User) -> bool:
        web = await self.for_user(user)
        if web is None:
            return False
        await self.set_active(web, False)
        return True

    async def authenticate(self, login: str, password: str) -> WebUser | None:
        web = await self.session.scalar(select(WebUser).where(WebUser.login == login.strip().lower()))
        if web is None or not web.active or not verify_password(password, web.password_hash):
            return None
        web.last_login_at = datetime.now(timezone.utc)
        await self.session.commit()
        return web

    # ---------- приглашения ----------

    async def create_invite(self, role: str, created_by: User) -> str:
        if role not in ROLES:
            raise ValueError(role)
        token = secrets.token_urlsafe(12)[:16]
        self.session.add(PanelInvite(token=token, role=role, created_by=created_by.id))
        await self.session.commit()
        return token

    async def accept_invite(self, token: str, user: User) -> tuple[str, str, str]:
        """→ (логин, пароль, роль). Ошибки: InviteError(invalid | used | expired)."""
        invite = await self.session.scalar(select(PanelInvite).where(PanelInvite.token == token))
        if invite is None:
            raise InviteError("invalid")
        if invite.used_at is not None:
            raise InviteError("used")
        if datetime.now(timezone.utc) - _aware(invite.created_at) > timedelta(days=INVITE_DAYS):
            raise InviteError("expired")
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by = user.id
        role = invite.role
        login, password = await self.issue_password(user, role=role)  # коммитит и приглашение
        return login, password, role
