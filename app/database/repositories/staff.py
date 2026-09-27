"""Сотрудники дилеров и приглашения."""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Dealer, DealerInvite, DealerStaff, User

INVITE_DAYS = 7


class InviteError(Exception):
    """reason: invalid | used | expired"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class StaffRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def dealer_id_for(self, user: User) -> int | None:
        return await self.session.scalar(select(DealerStaff.dealer_id).where(DealerStaff.user_id == user.id))

    async def staff_of(self, dealer_id: int) -> list[DealerStaff]:
        result = await self.session.scalars(
            select(DealerStaff).where(DealerStaff.dealer_id == dealer_id).order_by(DealerStaff.id)
        )
        return list(result.unique())

    async def create_invite(self, dealer_id: int) -> str:
        token = secrets.token_urlsafe(12)[:16]  # в ссылке /start разрешены только буквы, цифры, _ и -
        self.session.add(DealerInvite(token=token, dealer_id=dealer_id))
        await self.session.commit()
        return token

    async def accept_invite(self, token: str, user: User) -> Dealer:
        invite = await self.session.scalar(select(DealerInvite).where(DealerInvite.token == token))
        if invite is None:
            raise InviteError("invalid")
        if invite.used_at is not None:
            raise InviteError("used")
        if datetime.now(timezone.utc) - _aware(invite.created_at) > timedelta(days=INVITE_DAYS):
            raise InviteError("expired")
        staff = await self.session.scalar(select(DealerStaff).where(DealerStaff.user_id == user.id))
        if staff is None:
            self.session.add(DealerStaff(dealer_id=invite.dealer_id, user_id=user.id))
        else:
            staff.dealer_id = invite.dealer_id  # человек перешёл к другому дилеру
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by = user.id
        dealer = invite.dealer
        await self.session.commit()
        return dealer

    async def remove(self, staff_id: int) -> DealerStaff | None:
        staff = await self.session.get(DealerStaff, staff_id)
        if staff is not None:
            await self.session.delete(staff)
            await self.session.commit()
        return staff
