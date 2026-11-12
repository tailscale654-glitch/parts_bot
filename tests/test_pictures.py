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
    ("front wheel speed sensor", None, "wheel_speed_sensor"),  # главное слово английского — последнее, потом уточнение
    ("coolant temperature sensor", None, "sensor"),
    ("left front door lock assy", None, "lock"),            # «door lock» — замок, а не дверь
    ("left front door outer handle assy", None, "outer_handle"),
    ("rear row left safety belt assy", None, "seatbelt"),   # ремень безопасности ≠ приводной ремень
    ("air conditioner compressor belt", None, "belt"),
    ("FRONT WINDSHIELD", None, "windshield"),
    ("left front door glass assy", None, "door_glass"),
    ("headlamp assy left", None, "headlamp"),
    ("rear shock absorber assy", None, "shock"),
    ("down mounting soft pad", None, "cover"),              # «pad» без тормозов — не колодка
    ("1/2 gear synchronizer ring assembly", None, "synchronizer"),
    ("connecting rod bolt", None, "bolt"),
    ("drain screw plug washer", None, "washer"),
    ("gasket(oil drain plug)", None, "gasket"),              # пояснение в скобках не главное слово
    ("front fog lamp assy", None, "fog_lamp"),
    ("left rear combination lamp", None, "tail_lamp"),
    ("left front brake hose", None, "brake_line"),
    ("engine rear suspension cushion", None, "mount"),
    ("connecting rod bearing shell 1", None, "bearing_shell"),
    ("driver seat safety belt latch assy", None, "seatbelt"),
    ("wiper motor & bracket assy", None, "motor"),
    ("clutch driven plate", None, "clutch"),
    (None, "Сальник коленвала задний", "oil_seal"),
    (None, "Прокладка головки блока", "gasket"),
    (None, "Болт крепления колеса", "bolt"),
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
    families |= {key for _, _, key in pictures.SPECIFIC}
    assert families - set(PICS) == set()


def test_almost_every_known_part_gets_its_own_picture():
    names = json.loads((ROOT / "app/data/part_names.json").read_text(encoding="utf-8"))
    keys = [picture_key(en, tr.get("ru")) for en, tr in names.items()]
    assert sum(k != "part" for k in keys) / len(keys) > 0.98


def test_parts_are_spread_over_detailed_drawings():
    """Широкие группы («крышка», «кронштейн») не должны забирать львиную долю деталей."""
    names = json.loads((ROOT / "app/data/part_names.json").read_text(encoding="utf-8"))
    keys = [picture_key(en, tr.get("ru")) for en, tr in names.items()]
    broad = {"cover", "bracket", "body_panel", "hose", "trim", "fastener", "seal", "part"}
    assert sum(k in broad for k in keys) / len(keys) < 0.25
    assert len(set(keys)) > 120
