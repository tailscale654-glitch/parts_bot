"""VIN → автомобиль клиента из CarSale CRM: общая часть для бота (чат) и витрины (сканер)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.users import UserRepository
from app.services import cars
from app.services.carsale_crm import CrmUnavailable, SoldCar, crm
from app.services.localization import i18n

logger = logging.getLogger(__name__)

FOUND, MISSING, UNAVAILABLE = "found", "missing", "unavailable"


async def lookup(vin: str) -> tuple[str, SoldCar | None]:
    """(found, машина) — продана JAC Motors Toshkent; (missing, None) — нет в архиве;
    (unavailable, None) — CRM не ответила или не настроена (тогда сохраняем только VIN)."""
    try:
        sold = await crm().find_sold(vin)
    except CrmUnavailable as e:
        logger.warning("CarSale CRM: %s", e)
        return UNAVAILABLE, None
    return (FOUND, sold) if sold else (MISSING, None)


async def apply(session: AsyncSession, user: User, vin: str | None, sold: SoldCar | None) -> User:
    """Сохранить VIN; машину из CarSale — вместе с моделью, комплектацией, цветом, двигателем.
    Модели или цвета нет в боте — эти поля не трогаем (клиент выберет сам)."""
    fields: dict = {"vin": vin}
    if sold is not None:
        fields.update(engine=sold.engine or None, trim=sold.trim or None)
        if sold.model:
            fields.update(model=sold.model, modification=sold.mod, color=sold.color)
    return await UserRepository(session).set_car(user, **fields)


def card_lines(sold: SoldCar, lang: str | None) -> list[str]:
    """Строки карточки машины (для чата): модель · комплектация · цвет, двигатель, VIN."""
    title = " · ".join(filter(None, [sold.model or sold.carsale_model, cars.mod_name(sold.mod, lang),
                                     cars.color_name(sold.color, lang) or sold.carsale_color]))
    lines = [f"🚗 {title}"]
    if sold.trim:
        lines.append(i18n.t(lang, "vin_card_trim", trim=sold.trim))
    if sold.engine:
        lines.append(i18n.t(lang, "vin_card_engine", engine=sold.engine))
    lines.append(i18n.t(lang, "vin_card_vin", vin=sold.vin))
    return lines
