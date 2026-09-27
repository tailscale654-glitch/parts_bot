from decimal import Decimal

from app.database.models import Dealer, Stock, User
from app.database.repositories.admin import AdminRepository
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import OrderRepository
from app.keyboards.admin import AdminCB, admin_menu_keyboard, order_tabs
from tests.test_offers_cart import db  # noqa: F401


async def make_orders(db):
    user = await db.get(User, 1)
    user.phone = "+998901234567"
    cart = CartRepository(db)
    await cart.add(user, await db.get(Stock, 1))
    await cart.add(user, await db.get(Stock, 2))
    orders = await OrderRepository(db).create_from_cart(user)  # 2 заказа (2 дилера)
    await db.commit()
    return user, orders


async def test_order_counts_and_tabs(db):
    user, orders = await make_orders(db)
    repo = AdminRepository(db)
    await OrderRepository(db).set_status(orders[0], "CONFIRMED")
    await db.commit()
    counts = await repo.order_counts()
    assert counts == {"new": 1, "work": 1, "done": 0, "cancel": 0, "all": 2}

    items, total = await repo.orders_page("work", 0, 10)
    assert total == 1 and items[0].status == "CONFIRMED"
    items, total = await repo.orders_page("all", 0, 1)
    assert total == 2 and len(items) == 1 and items[0].id == max(o.id for o in orders)  # новые сверху

    tabs = order_tabs("ru", counts, "new")
    assert tabs[0][0].text == "• 🟡 Новые (1)" and tabs[0][1].text == "🔄 В работе (1)"
    assert AdminCB.unpack(tabs[1][2].callback_data).f == "all"
    assert admin_menu_keyboard("ru", 1).inline_keyboard[0][0].text == "🛒 Заказы (1 новых)"


async def test_dealers_and_toggle(db):
    await make_orders(db)
    repo = AdminRepository(db)
    rows, total = await repo.dealers_page(0, 10)
    assert total == 5
    by_name = {r.dealer.name: r for r in rows}
    assert by_name["JAC Ташкент №1"].offers == 1 and by_name["JAC Ташкент №1"].orders == 1
    assert by_name["JAC Ташкент №3"].offers == 0  # нет в наличии

    dealer = await repo.toggle_dealer(1)
    assert dealer.enabled is False
    assert (await db.get(Dealer, 1)).enabled is False
    assert (await repo.toggle_dealer(1)).enabled is True


async def test_catalog_summary(db):
    s = await AdminRepository(db).catalog_summary()
    assert s.parts_active == 1 and s.parts_hidden == 0
    assert s.offers_in_stock == 3 and s.dealers_with_stock == 3  # неактивный дилер №5 не считается
    assert s.by_model == [("JAC JS4", 1)] and s.by_node == [("Двигатель", 1)]


async def test_clients(db):
    user, orders = await make_orders(db)
    await OrderRepository(db).set_status(orders[0], "CANCELLED")
    await db.commit()
    repo = AdminRepository(db)
    assert await repo.clients_total() == (2, 1)  # второй пользователь без телефона
    rows, total = await repo.clients_page(0, 10)
    assert total == 1 and rows[0].user.id == user.id and rows[0].orders == 2
    assert rows[0].spent == sum(o.total_amount for o in orders[1:])  # отменённый не считается
    assert isinstance(rows[0].spent, Decimal)
