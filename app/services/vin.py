"""VIN автомобиля: проверка и распознавание с фото (штрих-код / QR или напечатанный текст).

VIN — 17 латинских букв и цифр без I, O и Q. 9-й знак — контрольная цифра (у китайских VIN, в том числе JAC,
она есть, как и у американских): по ней видно, что номер прочитан или набран без ошибок.

Распознавание (всё на нашем сервере, фото нигде не сохраняется):
  1. штрих-код или QR (наклейка на стойке двери, некоторые документы) — библиотека zxing-cpp;
  2. текст (техпаспорт, табличка под лобовым стеклом) — Tesseract OCR, если он установлен (в Docker-образе есть):
     находим строку с номером, перечитываем её 9 способами и выбираем номер, за который больше «голосов».
     Помогают правила VIN: контрольная цифра, 10-й знак — год (буква), у JAC начало «LJ1» и 6 цифр в конце.
     Итог всё равно сверяет клиент — витрина подставляет номер в поле, а не сохраняет сама.
"""
from __future__ import annotations

import io
import logging
import re
import shutil

logger = logging.getLogger(__name__)

ALLOWED = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_VALUES = {**{str(d): d for d in range(10)},
           **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
           **dict(zip("STUVWXYZ", range(2, 10)))}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
MAX_UPLOAD = 10 * 1024 * 1024  # 10 МБ — фото с телефона после сжатия в витрине обычно 0,3–1 МБ


def normalize(text: str | None) -> str:
    """Без пробелов и дефисов, заглавными; I → 1, O и Q → 0 (в VIN этих букв не бывает)."""
    text = re.sub(r"[\s\-_.:]", "", (text or "").upper())
    return text.translate(str.maketrans({"I": "1", "O": "0", "Q": "0"}))


def is_valid(vin: str | None) -> bool:
    """17 допустимых знаков, последние 4 — цифры (так требует стандарт ISO 3779)."""
    return bool(vin) and bool(VIN_RE.match(vin)) and vin[-4:].isdigit()


def check_digit_ok(vin: str) -> bool:
    if not is_valid(vin):
        return False
    total = sum(_VALUES[ch] * w for ch, w in zip(vin, _WEIGHTS))
    expected = "X" if total % 11 == 10 else str(total % 11)
    return vin[8] == expected


def _score(vin: str) -> int:
    score = 10 if check_digit_ok(vin) else 0
    score += 3 if vin.startswith("L") else 0  # китайский производитель (JAC — LJ1…)
    score += 2 if vin.startswith("LJ") else 0
    score += 2 if vin[-4:].isdigit() else 0  # серийный номер в конце — цифры
    score += 1 if any(c.isalpha() for c in vin) and any(c.isdigit() for c in vin) else 0
    return score


def find_vin(text: str | None) -> str | None:
    """Лучший VIN в распознанном тексте («VIN: LJ1 2EKR1 …», мусор вокруг, пробелы внутри) или None."""
    best, best_score = None, -1
    for line in (text or "").upper().splitlines() + [(text or "").upper()]:
        chars = normalize(re.sub(r"[^A-Z0-9]", "", line))
        for i in range(0, max(len(chars) - 16, 0)):
            cand = chars[i:i + 17]
            if not is_valid(cand):
                continue
            score = _score(cand)
            if score > best_score:
                best, best_score = cand, score
    return best


def _open(data: bytes):
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 50_000_000  # защита от «бомб» — огромных картинок
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    img = img.convert("RGB")
    img.thumbnail((2000, 2000))
    return img


def _from_barcode(img) -> str | None:
    try:
        import zxingcpp
    except ImportError:
        return None
    for result in zxingcpp.read_barcodes(img):
        vin = find_vin(result.text)
        if vin:
            return vin
    return None


def _gray(img, size: int = 1600):
    """Серое фото одного размера для поиска строк (мелкое увеличиваем, огромное уменьшаем) и коэффициент."""
    from PIL import Image, ImageFilter, ImageOps

    gray = ImageOps.grayscale(img)
    k = size / max(gray.size)
    if abs(k - 1) > .05:
        gray = gray.resize((round(gray.width * k), round(gray.height * k)), Image.LANCZOS)
    else:
        k = 1.0
    return gray.filter(ImageFilter.MedianFilter(3)), k  # медиана убирает «зерно» камеры, буквы не трогает


def _otsu(gray):
    """Чёрно-белая версия с порогом Оцу — помогает на бликах и цветном фоне."""
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * c for i, c in enumerate(hist))
    best, threshold, w_b, sum_b = -1.0, 128, 0, 0
    for i, c in enumerate(hist):
        w_b += c
        if not w_b or w_b == total:
            continue
        sum_b += i * c
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / (total - w_b)
        between = w_b * (total - w_b) * (m_b - m_f) ** 2
        if between > best:
            best, threshold = between, i
    return gray.point(lambda p: 255 if p > threshold else 0)


def _tesseract(image, psm: int, whitelist: bool = False):
    import pytesseract

    config = f"--psm {psm}" + (" -c tessedit_char_whitelist=" + ALLOWED + "IOQ" if whitelist else "")
    try:
        return pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT, timeout=10)
    except Exception as e:  # noqa: BLE001 — таймаут или сбой Tesseract: этот вариант пропускаем
        logger.warning("VIN OCR failed: %s", e)
        return None


def _lines(data) -> list[tuple[list[str], tuple[int, int, int, int], int]]:
    """Слова Tesseract → строки (слова слева направо, рамка строки, высота букв)."""
    if not data:
        return []
    words = [(data["text"][i].strip(), data["left"][i], data["top"][i], data["width"][i], data["height"][i])
             for i in range(len(data["text"])) if data["text"][i].strip()]
    rows: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: w[2] + w[4] / 2):
        mid = w[2] + w[4] / 2
        row = rows[-1] if rows else None
        if row and abs(mid - sum(x[2] + x[4] / 2 for x in row) / len(row)) < max(x[4] for x in row) * .6:
            row.append(w)
        else:
            rows.append([w])
    out = []
    for row in rows:
        row.sort(key=lambda w: w[1])
        box = (min(w[1] for w in row), min(w[2] for w in row),
               max(w[1] + w[3] for w in row), max(w[2] + w[4] for w in row))
        out.append(([w[0] for w in row], box, sorted(w[4] for w in row)[len(row) // 2]))
    return out


# Знаки, которые OCR чаще всего путает между собой
_LOOKALIKE = {"S": "5", "5": "S", "B": "8", "8": "B", "G": "6", "6": "G", "Z": "2", "2": "Z", "D": "0", "0": "D",
              "T": "7", "7": "T", "A": "4", "4": "A", "L": "1", "1": "L", "U": "V", "V": "U"}
_TO_DIGIT = str.maketrans({k: v for k, v in _LOOKALIKE.items() if k.isalpha() and v.isdigit()})


def _lookalike_fix(vin: str) -> str | None:
    """Одна перепутанная пара (S↔5, B↔8, G↔6, Z↔2, D↔0…) — если ровно одна замена даёт верную контрольную цифру."""
    fixes = {fixed for i, ch in enumerate(vin) if ch in _LOOKALIKE
             for fixed in [vin[:i] + _LOOKALIKE[ch] + vin[i + 1:]] if is_valid(fixed) and check_digit_ok(fixed)}
    return fixes.pop() if len(fixes) == 1 else None


def _jac_fix(vin: str) -> str | None:
    """«LJL…», «LY1…», «L31…» → «LJ1…»: у JAC номер начинается с LJ1, а «1» и «J» OCR путает чаще всего.
    Чиним, только если после замены сошлась контрольная цифра."""
    if vin[:3] == "LJ1" or sum(a != b for a, b in zip(vin[:3], "LJ1")) != 1:
        return None
    fixed = "LJ1" + vin[3:]
    return fixed if check_digit_ok(fixed) else None


def _candidates(words: list[str]) -> dict[str, float]:
    """VIN-кандидаты в строке и их вес: целое «слово» (или 2–4 слова подряд) из 17 знаков — 1; лишний знак
    в начале «LJ1» (OCR видит «1» как «IL») — 0,6; 17 знаков от края более длинного слова — 0,4."""
    tokens = [normalize(re.sub(r"[^A-Z0-9]", "", w.upper())) for w in words]
    tokens = [t for t in tokens if t]
    found: dict[str, float] = {}
    bonus = .5 if any(t[:3] in ("V1N", "V0N") for t in tokens) else 0  # в строке есть подпись «VIN»

    def add(vin: str, weight: float) -> None:
        if vin[9] == "1":  # 10-й знак — год выпуска: «1» значило бы 2001 или 2031 год, это «J» (2018)
            vin = vin[:9] + "J" + vin[10:]
        if vin.startswith("LJ1"):  # у JAC (как у всех китайских VIN) последние 6 знаков — цифры
            vin = vin[:11] + vin[11:].translate(_TO_DIGIT)
        if is_valid(vin) and vin[:3] not in ("V1N", "V0N"):
            found[vin] = max(found.get(vin, 0), weight + bonus)

    tokens = [t[3:] if t[:3] in ("V1N", "V0N") and len(t) > 17 else t for t in tokens]  # «VIN:LJ1…» слитно
    for i in range(len(tokens)):
        acc = ""
        for t in tokens[i:i + 4]:  # номер, разбитый пробелами на части
            acc += t
            if len(acc) >= 17:
                break
        if len(acc) == 17:
            add(acc, 1.0)
        elif len(acc) == 18 and acc.startswith("LJ"):
            for j in range(2, 5):
                cand = acc[:j] + acc[j + 1:]
                if cand.startswith("LJ1") and check_digit_ok(cand):
                    add(cand, .6)
    run, edges, pos = "", set(), 0
    for t in tokens:
        edges.add(pos)
        run += t
        pos += len(t)
    edges.add(pos)
    for i in range(max(len(run) - 16, 0)):
        if i in edges or i + 17 in edges:  # окно, разрезающее слово с двух сторон, — почти всегда мусор
            add(run[i:i + 17], .4)
    for vin, weight in list(found.items()):
        fixed = None if check_digit_ok(vin) else _jac_fix(vin) or _lookalike_fix(vin)
        if fixed:
            add(fixed, (weight - bonus) * .9)
    return found


def _from_text(img) -> str | None:
    """Напечатанный номер: 1) находим строку с VIN на всём фото; 2) перечитываем только её — в нескольких
    масштабах и вариантах — и выбираем номер, за который «проголосовало» больше всего прочтений."""
    if shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return None
    from PIL import Image, ImageFilter, ImageOps

    votes: dict[str, float] = {}

    def vote(found: dict[str, float]) -> None:
        for vin, weight in found.items():
            votes[vin] = votes.get(vin, 0) + weight

    full = ImageOps.grayscale(img).filter(ImageFilter.MedianFilter(3))  # строку перечитываем в полном разрешении
    base, k_base = _gray(img)
    lines = []
    for angle in (0, 90, 270):  # документ могли снять боком
        page = base.rotate(angle, expand=True) if angle else base
        found = _lines(_tesseract(page, 11))
        lines = [line for line in found if len(re.sub(r"[^A-Z0-9]", "", "".join(line[0]).upper())) >= 14]
        if lines:
            break
    source = full.rotate(angle, expand=True) if angle else full
    # строки, похожие на VIN, — сначала те, где уже есть кандидат
    lines.sort(key=lambda line: -max(_candidates(line[0]).values(), default=0))
    for words, box, height in lines[:2]:
        vote(_candidates(words))
        left, top, right, bottom = (round(v / k_base) for v in box)
        height = height / k_base
        # полоса шире найденных слов: начало или конец номера могли не распознаться при поиске
        side, pad = round(height * 8), round(max(height * .8, 6))
        crop = source.crop((max(left - side, 0), max(top - pad, 0), min(right + side, source.width),
                            min(bottom + pad, source.height)))
        for target in (30, 40, 52):  # высота букв, на которой Tesseract читает лучше всего
            k = target / max(height, 1)
            line_img = crop.resize((max(round(crop.width * k), 1), max(round(crop.height * k), 1)), Image.LANCZOS)
            for variant, whitelist in ((line_img, False), (line_img, True), (_otsu(line_img), True)):
                for words2, _, _ in _lines(_tesseract(variant, 7, whitelist)):
                    vote(_candidates(words2))
    if not votes:
        return None

    def rank(vin: str) -> float:  # совпавшая контрольная цифра удваивает голоса (но не больше +2)
        return votes[vin] + (min(votes[vin], 2) if check_digit_ok(vin) else 0) + (.3 if vin.startswith("LJ1") else 0)

    return max(votes, key=rank)


def read_vin(data: bytes) -> tuple[str | None, str | None]:
    """Фото → (VIN, «barcode» | «text») или (None, None). Тяжёлая работа — вызывать в отдельном потоке."""
    try:
        img = _open(data)
    except Exception as e:  # noqa: BLE001 — не картинка или повреждённый файл
        logger.info("VIN photo is not an image: %s", e)
        return None, None
    vin = _from_barcode(img)
    if vin:
        return vin, "barcode"
    vin = _from_text(img)
    return (vin, "text") if vin else (None, None)
