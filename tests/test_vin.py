"""VIN: проверка номера и распознавание с фото (штрих-код, QR, напечатанный текст)."""
import io
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services import cars
from app.services.vin import check_digit_ok, find_vin, is_valid, normalize, read_vin

VIN = "LJ12EKR17N4000123"  # контрольная цифра (9-й знак) сходится
zxingcpp = pytest.importorskip("zxingcpp")


def barcode_png(text: str, fmt) -> bytes:
    """Штрих-код как на наклейке VIN — делаем той же библиотекой, что и читает (разные версии API)."""
    if hasattr(zxingcpp, "create_barcode"):
        raw = memoryview(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(text, fmt), scale=3))
        img = Image.frombytes("L", (raw.shape[1], raw.shape[0]), raw.tobytes())
    else:
        img = Image.fromarray(zxingcpp.write_barcode(fmt, text, width=700, height=160))
    canvas = Image.new("L", (img.width + 80, img.height + 80), 255)  # белые поля, как на наклейке
    canvas.paste(img, (40, 40))
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


def test_normalize_and_validate():
    assert normalize(" lj1 2ekr1-7n4o00123 ") == VIN  # пробелы, дефис, маленькие буквы, O вместо 0
    assert normalize("LJI2EKRI7N4000I23") == VIN  # I читается как 1
    assert is_valid(VIN) and check_digit_ok(VIN)
    assert check_digit_ok("1HGCM82633A004352")  # американский пример со стандартной контрольной цифрой
    assert is_valid("LJ12EKR15N4000123") and not check_digit_ok("LJ12EKR15N4000123")  # опечатка видна по 9-му знаку
    for bad in ("", "LJ12EKR17N400012", "LJ12EKR17N40001234", "LJ12EKR17N40001A3", "ЛJ12EKR17N4000123", None):
        assert not is_valid(bad)


def test_find_vin_in_text():
    assert find_vin(f"СВИДЕТЕЛЬСТВО\nИдентификационный номер (VIN): {VIN}\nМарка JAC") == VIN
    assert find_vin("VIN: LJ1 2EKR1 7N4 000123") == VIN  # OCR разбил номер пробелами
    assert find_vin("ABCDEFGHJKLMNPRST mixed noise 12") is None  # 17 букв без цифр в конце — не VIN
    assert find_vin("") is None and find_vin(None) is None


@pytest.mark.parametrize("fmt", ["Code128", "Code39", "QRCode", "DataMatrix"])
def test_read_vin_from_barcode(fmt):
    vin, method = read_vin(barcode_png(VIN, getattr(zxingcpp.BarcodeFormat, fmt)))
    assert (vin, method) == (VIN, "barcode")


def test_read_vin_rejects_junk():
    assert read_vin(b"not an image") == (None, None)
    assert read_vin(barcode_png("HELLO WORLD 123", zxingcpp.BarcodeFormat.Code128)) in ((None, None),)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract не установлен (в Docker-образе есть)")
def test_read_vin_from_printed_text():
    font_path = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                  "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf") if Path(p).exists()), None)
    if font_path is None:
        pytest.skip("нет шрифта для картинки")
    img = Image.new("RGB", (1100, 260), (236, 232, 222))  # бумага техпаспорта
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "IDENTIFICATION NUMBER", fill=(90, 90, 90), font=ImageFont.truetype(font_path, 30))
    draw.text((40, 110), f"VIN {VIN}", fill=(20, 20, 20), font=ImageFont.truetype(font_path, 54))
    out = io.BytesIO()
    img.rotate(1.5, expand=True, fillcolor=(236, 232, 222)).save(out, "JPEG", quality=85)
    assert read_vin(out.getvalue()) == (VIN, "text")


def test_car_with_vin():
    user = SimpleNamespace(car_model="JAC M3", car_modification="van", car_color="white", car_vin=VIN)
    assert cars.car_with_vin(user, "ru") == f"{cars.car_text(user, 'ru')} · VIN {VIN}"
    user.car_model = user.car_modification = user.car_color = None
    assert cars.car_with_vin(user, "ru") == f"VIN {VIN}"
    user.car_vin = None
    assert cars.car_with_vin(user, "ru") is None
