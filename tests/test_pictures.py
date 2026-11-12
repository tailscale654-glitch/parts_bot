"""Схематичные рисунки деталей: какая деталь какой рисунок получает и что рисунок существует."""
import json
import re
from pathlib import Path

import pytest

from app.services import pictures
from app.services.pictures import picture_key

ROOT = Path(__file__).resolve().parent.parent
PICS = json.loads(re.search(r"window\.PICS = (\{.*\});", (ROOT / "app/miniapp/static/pics.js").read_text(encoding="utf-8"),
                            re.S).group(1))


@pytest.mark.parametrize("name_en, name_ru, expected", [
    ("ENGINE OIL FILTER ASSY.", "Масляный фильтр", "oil_filter"),
    ("FRONT BRAKE PAD ASSY.", "Колодки тормозные передние", "brake_pad"),
    ("front wheel speed sensor", None, "sensor"),          # главное слово английского — последнее
    ("left front door lock assy", None, "lock"),            # «door lock» — замок, а не дверь
    ("left front door outer handle assy", None, "handle"),
    ("rear row left safety belt assy", None, "seatbelt"),   # ремень безопасности ≠ приводной ремень
    ("air conditioner compressor belt", None, "belt"),
    ("FRONT WINDSHIELD", None, "glass"),
    ("headlamp assy left", None, "headlamp"),
    ("rear shock absorber assy", None, "shock"),
    ("down mounting soft pad", None, "cover"),              # «pad» без тормозов — не колодка
    ("1/2 gear synchronizer ring assembly", None, "gear"),
    (None, "Датчик давления масла", "sensor"),              # русское: главное слово — первое
    (None, "Стойка амортизатора передняя", "shock"),
    (None, "Фильтр топливный", "fuel_filter"),
    (None, "Подушка безопасности водителя", "airbag"),
    ("xyz-123", "Что-то непонятное", "part"),               # не узнали — просто «деталь»
])
def test_picture_key(name_en, name_ru, expected):
    assert picture_key(name_en, name_ru) == expected


def test_every_family_has_a_drawing():
    families = {pictures.DEFAULT} | set(pictures.HEAD1.values()) | set(pictures.HEAD2.values())
    families |= {key for _, key in pictures.RU_FIRST} | {key for _, key in pictures.KEYWORDS}
    families |= {refined for _, _, refined in pictures.REFINE} | {"cover"}
    assert families - set(PICS) == set()


def test_almost_every_known_part_gets_its_own_picture():
    names = json.loads((ROOT / "app/data/part_names.json").read_text(encoding="utf-8"))
    keys = [picture_key(en, tr.get("ru")) for en, tr in names.items()]
    assert sum(k != "part" for k in keys) / len(keys) > 0.98
