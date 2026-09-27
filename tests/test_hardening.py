from pathlib import Path

from sqlalchemy import select

from app.database.models import Stock, User
from app.database.repositories.cart import CartRepository
from app.database.repositories.orders import OrderRepository
from app.handlers.admin_panel import latest_backup
from app.services.alerts import ErrorAlerts
from app.services.excel_import import validate_any, apply_import
from tests.test_excel_import import REGIONS, make_xlsx  # noqa: F401
from tests.test_offers_cart import db  # noqa: F401


def boom():
    raise ValueError("broken")


def test_error_alerts_throttled():
    alerts = ErrorAlerts(window=600)
    try:
        boom()
    except ValueError as e:
        exc = e
    assert alerts.should_send(exc, now=0) is True
    assert alerts.should_send(exc, now=100) is False  # та же ошибка в течение 10 минут — молчим
    assert alerts.should_send(exc, now=700) is True
    text = alerts.text(exc, update_id=42)
    assert "ValueError: broken" in text and "update_id: 42" in text and "boom" in text


def test_latest_backup(tmp_path: Path):
    assert latest_backup(tmp_path / "nope") is None
    assert latest_backup(tmp_path) is None
    for name in ("jac_parts_2026-09-26_0300.sql.gz", "jac_parts_2026-09-27_0300.sql.gz", "other.txt"):
        (tmp_path / name).write_text("x")
    assert latest_backup(tmp_path).name == "jac_parts_2026-09-27_0300.sql.gz"


async def test_import_subtracts_open_orders(db, tmp_path):
    """Клиент заказал 3 шт. у дилера №2 (заказ не закрыт). В новом файле у дилера 4 шт. → в боте 1 шт."""
    user = await db.get(User, 1)
    cart = CartRepository(db)
    for _ in range(3):
        await cart.add(user, await db.get(Stock, 2))
    order = (await OrderRepository(db).create_from_cart(user))[0]
    await db.commit()

    row = {"region": "Ташкент", "dealer": "JAC Ташкент №2", "model_ru": "JAC JS4", "node_ru": "Двигатель",
           "part_name_ru": "Масляный фильтр", "part_number": "101001", "price": "82000", "stock": "4"}
    regions = [type(REGIONS[0])(id=1, code="tashkent_city", name_ru="Ташкент")]
    rows, errors, _, _ = validate_any(make_xlsx(tmp_path, [row]), regions)
    assert errors == []
    stats = await apply_import(db, rows)
    await db.commit()
    stock = await db.scalar(select(Stock).where(Stock.dealer_id == 2))
    assert stock.quantity == 1 and stats.reserved == 3

    # заказ выдан → больше не резерв: следующая загрузка ставит остаток как в файле
    await OrderRepository(db).set_status(order, "CONFIRMED")
    await OrderRepository(db).set_status(order, "READY")
    await OrderRepository(db).set_status(order, "COMPLETED")
    await db.commit()
    stats = await apply_import(db, rows)
    await db.commit()
    assert (await db.get(Stock, stock.id)).quantity == 4 and stats.reserved == 0
