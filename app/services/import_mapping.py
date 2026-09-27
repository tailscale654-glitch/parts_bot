"""Настройки импорта складской выгрузки («Список запчастей», лист «Запчасти»).

Этот файл можно править без знания Python — меняйте только текст в кавычках.
После правки: git push → на сервере git pull && docker compose up -d --build.
"""

# Какую цену показывать покупателю. Если в строке она 0 — берётся вторая.
PRICE_COLUMN = "Цена реализации"
FALLBACK_PRICE_COLUMN = "Цена продажи"

# Какие строки считаются «в наличии у дилера».
# «Бронь для заказа», «Запчасть реализована», «Перемещение к дилеру», «На складе» — не показываем.
AVAILABLE_STATUSES = {"У дилера"}

# Тип запчасти → категория в боте (русский, английский, узбекский)
CATEGORIES = {
    "A": ("ТО и расходники", "Maintenance & consumables", "Texnik xizmat va sarf materiallari"),
    "B": ("Кузов", "Body", "Kuzov"),
    "C": ("Тормоза и ходовая", "Brakes & suspension", "Tormoz va yurish qismi"),
    "D": ("Электрика и электроника", "Electrics & electronics", "Elektr va elektronika"),
    "TOOLS": ("Инструменты", "Tools", "Asboblar"),
}
OTHER_CATEGORY = ("Прочее", "Other", "Boshqa")

# Детали, у которых модель не указана («—»), попадают сюда
ALL_MODELS = ("Все модели", "All models", "Barcha modellar")

# Заводской код модели → название в боте. Код, которого здесь нет, покажется как есть.
# ⚠️ Проверьте: названия ниже — предположения по кодам.
MODEL_NAMES = {
    "T8-P30BF": "JAC T8",
    "T9-P33Z3": "JAC T9",
    "JS8P-S55NG": "JAC JS8 Pro",
    "M3": "JAC M3",
    "M4": "JAC M4",
    "Sunray": "JAC Sunray",
    "RF8-V9AA3": "JAC RF8 (V9AA3)",
    "RF8-V9HA0": "JAC RF8 (V9HA0)",
}

# Дилер (как в колонке «На Дилера») → регион в боте.
# Коды регионов: tashkent_city, tashkent, samarkand, bukhara, andijan, fergana, namangan,
# kashkadarya, surkhandarya, khorezm, karakalpakstan, jizzakh, navoi, syrdarya
# ⚠️ Заполнено по названиям (догадки). Дилеры, которых здесь нет, попадут в DEFAULT_REGION.
DEALER_REGIONS = {
    "ООО «Navoiy Avtotrans xizmat»": "navoi",
    "ООО «BILLUR MOTORS QIZILTEPA»": "navoi",
    "OOO «AUTOCENTER NURAFSHON»": "tashkent",
    "OOO «NURAFSHON AUTO ZONE»": "tashkent",
    "ООО «TOSHKENT-MOTORS-TRADE»": "tashkent_city",
}
DEFAULT_REGION = "tashkent_city"
