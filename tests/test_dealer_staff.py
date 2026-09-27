from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import Settings
from app.database.models import DealerInvite, Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import OrderRepository
from app.database.repositories.staff import InviteError, StaffRepository
from app.handlers.chat import can_write
from app.keyboards.main import main_reply_keyboard, menu_action
from tests.test_offers_cart import db  # noqa: F401

SETTINGS = Settings(bot_token="x", admin_ids={1000}, database_url="")


async def test_invite_flow(db):
    staff_user = await db.get(User, 2)
    repo = StaffRepository(db)
    token = await repo.create_invite(dealer_id=1)
    assert len(token) == 16 and all(c.isalnum() or c in "-_" for c in token)  # годится для ссылки /start

    dealer = await repo.accept_invite(token, staff_user)
    assert dealer.id == 1 and await repo.dealer_id_for(staff_user) == 1
    with pytest.raises(InviteError) as e:
        await repo.accept_invite(token, staff_user)  # одноразовая
    assert e.value.reason == "used"
    with pytest.raises(InviteError) as e:
        await repo.accept_invite("nope", staff_user)
    assert e.value.reason == "invalid"

    old = await repo.create_invite(dealer_id=2)
    invite = await db.scalar(select(DealerInvite).where(DealerInvite.token == old))
    invite.created_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db.commit()
    with pytest.raises(InviteError) as e:
        await repo.accept_invite(old, staff_user)
    assert e.value.reason == "expired"

    # новое приглашение другого дилера — человек переходит к нему (один дилер на человека)
    await repo.accept_invite(await repo.create_invite(dealer_id=2), staff_user)
    assert await repo.dealer_id_for(staff_user) == 2
    assert [s.user.id for s in await repo.staff_of(2)] == [2] and await repo.staff_of(1) == []

    staff = (await repo.staff_of(2))[0]
    await repo.remove(staff.id)
    assert await repo.dealer_id_for(staff_user) is None


async def test_who_can_write_and_change(db):
    client = await db.get(User, 1)
    await CartRepository(db).add(client, await db.get(Stock, 1))  # дилер №1
    order = (await OrderRepository(db).create_from_cart(client))[0]
    await db.commit()
    stranger = await db.get(User, 2)
    admin = User(id=99, telegram_id=1000)

    assert can_write(order, "dealer", client, SETTINGS, None)  # клиент → своему дилеру
    assert not can_write(order, "client", client, SETTINGS, None)
    assert can_write(order, "client", stranger, SETTINGS, staff_dealer_id=1)  # сотрудник этого дилера
    assert not can_write(order, "client", stranger, SETTINGS, staff_dealer_id=2)  # сотрудник другого дилера
    assert not can_write(order, "dealer", stranger, SETTINGS, None)  # чужой клиент
    assert can_write(order, "client", admin, SETTINGS, None)  # администратор
    assert not can_write(None, "dealer", client, SETTINGS, None)


def test_staff_menu_button():
    kb = main_reply_keyboard("uz", staff=True)
    assert kb.keyboard[0][0].text == "📋 Diler buyurtmalari" and len(kb.keyboard) == 4
    assert len(main_reply_keyboard("uz").keyboard) == 3
    assert menu_action("📋 Заказы дилера") == "btn_dealer_orders"
