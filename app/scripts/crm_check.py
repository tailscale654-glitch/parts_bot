"""Проверка связи с CarSale CRM: найти проданную машину по VIN.

На сервере:  docker compose exec bot python -m app.scripts.crm_check LJ166A257T4020777
Логин и пароль берутся из .env (CARSALE_CRM_LOGIN / CARSALE_CRM_PASSWORD или CARSALE_LOGIN / CARSALE_PASSWORD).
"""
import asyncio
import sys

from app.services.carsale_crm import CrmUnavailable, close_crm, crm
from app.services.vin import is_valid, normalize


async def main(vin: str) -> int:
    vin = normalize(vin)
    if not is_valid(vin):
        print("Это не VIN: нужно 17 латинских букв и цифр.")
        return 2
    try:
        car = await crm().find_sold(vin)
    except CrmUnavailable as e:
        print(f"❌ CarSale CRM: {e}")
        return 1
    finally:
        await close_crm()
    if car is None:
        print(f"✅ Связь есть. VIN {vin} не найден среди проданных («Остатки» → «Архив»).")
        return 0
    print(f"✅ Найдено: {car.carsale_model} · {car.trim} · {car.carsale_color}")
    print(f"   В боте: {car.model or '— (модели нет в боте)'} · {car.mod or '-'} · {car.color or '— (цвет выберет клиент)'}")
    print(f"   Двигатель №: {car.engine or '—'}   Выпуск: {car.produced or '—'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
