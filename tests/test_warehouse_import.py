"""Складская выгрузка «Список запчастей» (лист «Запчасти», заголовки на 4-й строке)."""
from decimal import Decimal

from openpyxl import Workbook

from app.database.models import Region
from app.services.excel_import import _model_names, validate_any

HEADER = ["№", "Кол-во", "Код запчасти", "Название запчасти", "Статус", "Тип запчасти", "Автомобильная марка",
          "Цена продажи", "Цена реализации", "Склад", "Ячейка", "Инвойс", "На Дилера", "Последнее перемещение",
          "Дата обновления"]
REGIONS = [Region(id=i, code=c, name_ru=c) for i, c in enumerate(
    ["tashkent_city", "tashkent", "samarkand", "navoi"], start=1)]


def make_export(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Запчасти"
    ws.append(["Список запчастей"])
    ws.append(["Выгрузка от 27.09.2026 · 5 записей"])
    ws.append([])
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    ws.append(["x̄  СРЕДНЕЕ"])  # итоговая строка внизу — должна игнорироваться
    path = tmp_path / "export.xlsx"
    wb.save(path)
    return path


def row(qty, code, name, status, typ, model, sale, real, dealer, date="25.09.2026 18:00:00"):
    return [1, qty, code, name, status, typ, model, sale, real, "—", "—", "INV", dealer, "", date]


def test_model_code_lists():
    assert [m[0] for m in _model_names("T9-P33Z3,T8-P30BF")] == ["JAC T9", "JAC T8"]
    assert [m[0] for m in _model_names("RF8-V9AA3,V9HA0")] == ["JAC RF8"]  # две комплектации — одна модель
    assert [m[0] for m in _model_names("JS8P-S55NG")] == ["JAC JS8"]
    assert [m[0] for m in _model_names("M4")] == ["JAC M4 Luxe"]
    assert _model_names("—")[0] == ("Все модели", "All models", "Barcha modellar")
    assert _model_names("XYZ-1")[0][0] == "XYZ-1"  # неизвестный код — как есть


def test_warehouse_export(tmp_path):
    path = make_export(tmp_path, [
        row(2, "1026301V02H4", "ECU", "У дилера", "D", "M3", 1587700, 1905125, "OOO «China Group»", "25.09.2026 10:00:00"),
        row(3, "1026301V02H4", "ECU", "У дилера", "D", "M3", 1587700, 1999000, "OOO «China Group»", "26.09.2026 10:00:00"),
        row(5, "1015601GD190", "GENERATOR BELT", "У дилера", "A", "—", 72870, 0, "ООО «Navoiy Avtotrans xizmat»"),
        row(1, "5206100P3010", "FRONT WINDSHIELD", "Бронь для заказа", "B", "T8-P30BF", 703815, 809445, "OOO «ASIAMOTOR»"),
        row(15, "3608100V670001", "BSM", "На складе", "D", "M4", 1193310, 1431911, "—"),
        row(1, "X1", "ODD PART", "У дилера", "ZZ", "T9-P33Z3,T8-P30BF", 100, 200, "OOO «ASIAMOTOR»"),
        row(1, "X2", "NEW MODEL PART", "У дилера", "A", "XYZ-9", 100, 200, "OOO «ASIAMOTOR»"),
    ])
    rows, errors, warnings, fmt = validate_any(path, REGIONS, {"navoiyavtotransxizmat": 4})  # Навои — из справочника
    assert fmt == "warehouse" and errors == []

    ecu = [r for r in rows if r.part_number == "1026301V02H4"]
    assert len(ecu) == 1 and ecu[0].stock == 5  # две строки одного дилера сложены
    assert ecu[0].price == Decimal("1999000")  # цена реализации из самой свежей строки
    assert ecu[0].model["ru"] == "JAC M3" and ecu[0].node["ru"] == "Электрика и электроника"
    assert ecu[0].region_id == 1  # China Group нет в справочнике → Ташкент

    belt = next(r for r in rows if r.part_number == "1015601GD190")
    assert belt.price == Decimal("72870")  # цена реализации 0 → цена продажи
    assert belt.model["ru"] == "Все модели" and belt.region_id == 4  # Навои

    odd = [r for r in rows if r.part_number == "X1"]
    assert sorted(r.model["ru"] for r in odd) == ["JAC T8", "JAC T9"] and odd[0].node["ru"] == "Прочее"

    unknown = next(w for w in warnings if w.key == "warn_unknown_models")
    assert unknown.params["models"] == "XYZ-9"
    keys = {(w.key, w.params.get("status")) for w in warnings}
    assert ("warn_skipped_status", "Бронь для заказа") in keys and ("warn_skipped_status", "На складе") in keys
    default = next(w for w in warnings if w.key == "warn_default_region")
    assert "China Group" in default.params["dealers"] and "Navoiy" not in default.params["dealers"]


def test_template_still_detected(tmp_path):
    from app.services.excel_template import build_template
    path = tmp_path / "t.xlsx"
    path.write_bytes(build_template())
    regions = [Region(id=1, code="tashkent_city", name_ru="Ташкент"), Region(id=3, code="samarkand", name_ru="Самаркандская область")]
    rows, errors, warnings, fmt = validate_any(path, regions)
    assert fmt == "template" and errors == [] and len(rows) == 3
