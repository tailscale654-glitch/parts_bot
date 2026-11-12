"""Схематичная картинка детали по её названию (сами рисунки — app/miniapp/static/pics.js).

Рисунки свои, в одном стиле: тонкие линии, без фото с чужих сайтов. Деталь получает рисунок своего
«семейства»: масляный фильтр, колодки, подшипник, фара, ручка двери… Если в панели задано настоящее
фото (поле «Фото»), показывается оно.

Как определяем семейство:
  1. английское название из CarSale: главное слово стоит в конце — «front wheel speed SENSOR», «door LOCK»;
  2. русское название: главное слово — первое — «ДАТЧИК скорости колеса»;
  3. не нашли — ищем ключевые слова по всему названию; совсем не нашли — «part» (просто деталь).
"""
import re

DEFAULT = "part"

# --- английский: два последних слова ---
HEAD2 = {
    "spark plug": "spark_plug", "glow plug": "spark_plug", "brake pad": "brake_pad", "brake shoe": "brake_pad",
    "brake disc": "brake_disc", "brake disk": "brake_disc", "brake drum": "brake_disc",
    "oil filter": "oil_filter", "fuel filter": "fuel_filter", "air filter": "air_filter", "cabin filter": "air_filter",
    "seat belt": "seatbelt", "safety belt": "seatbelt", "belt buckle": "seatbelt",
    "control arm": "arm", "swing arm": "arm", "tie rod": "rod", "ball joint": "rod", "rod end": "rod",
    "shock absorber": "shock", "wheel hub": "hub", "steering wheel": "steering", "steering gear": "steering",
    "steering column": "steering", "steering rack": "steering",
    "window regulator": "window_regulator", "glass regulator": "window_regulator",
    "wiper blade": "wiper", "wiper arm": "wiper", "wiper motor": "motor", "washer nozzle": "wiper",
    "air bag": "airbag", "fog lamp": "lamp", "fog light": "lamp", "head lamp": "headlamp", "tail lamp": "lamp",
    "door glass": "glass", "piston ring": "piston", "connecting rod": "piston", "oil seal": "seal", "o ring": "seal",
    "synchronizer ring": "gear", "snap ring": "fastener", "retaining ring": "fastener",
    "drive shaft": "shaft", "half shaft": "shaft", "engine oil": "fluid", "brake fluid": "fluid",
    "water pump": "pump", "oil pump": "pump", "fuel pump": "pump", "washer pump": "pump",
    "expansion tank": "tank", "fuel tank": "tank", "washer tank": "tank", "washer kettle": "tank",
    "clutch disc": "clutch", "clutch disk": "clutch", "pressure plate": "clutch", "release bearing": "bearing",
    "shift lever": "handle", "gear lever": "handle", "shift knob": "handle",
    "cylinder head": "engine", "cylinder block": "engine", "lock cylinder": "lock",
    "brake cylinder": "caliper", "master cylinder": "caliper", "wheel cylinder": "caliper", "slave cylinder": "caliper",
    "license plate": "cover", "number plate": "cover", "seat cushion": "seat", "engine cushion": "bracket",
    "side step": "trim", "rearview mirror": "mirror", "ignition coil": "module",
    "throttle body": "valve", "torsion bar": "rod", "stop block": "bracket", "ball cage": "bearing",
    "smart key": "key", "remote key": "key", "timing chain": "belt", "clock spring": "module",
}

# --- английский: последнее слово ---
HEAD1 = {
    **dict.fromkeys(["filter", "strainer"], "air_filter"),
    **dict.fromkeys(["pad", "shoe"], "brake_pad"),
    **dict.fromkeys(["disc", "disk", "rotor", "drum"], "brake_disc"),
    **dict.fromkeys(["caliper", "cylinder"], "caliper"),
    **dict.fromkeys(["bearing"], "bearing"),
    **dict.fromkeys(["gear", "gears", "synchronizer", "synchroniser", "sprocket", "differential"], "gear"),
    **dict.fromkeys(["shaft", "axle", "crankshaft", "camshaft", "countershaft", "spindle"], "shaft"),
    **dict.fromkeys(["belt"], "belt"),
    **dict.fromkeys(["pulley", "tensioner", "idler", "roller"], "pulley"),
    **dict.fromkeys(["pump", "compressor"], "pump"),
    **dict.fromkeys(["sensor", "probe"], "sensor"),
    **dict.fromkeys(["switch", "button"], "switch"),
    **dict.fromkeys(["controller", "ecu", "module", "unit", "relay", "radar", "computer", "amplifier", "inverter",
                     "fuse", "coil", "receiver", "transmitter", "box"], "module"),
    **dict.fromkeys(["harness", "wire", "wiring", "cable", "cord"], "harness"),
    **dict.fromkeys(["headlamp", "headlight"], "headlamp"),
    **dict.fromkeys(["lamp", "light", "lantern", "indicator", "repeater"], "lamp"),
    **dict.fromkeys(["mirror"], "mirror"),
    **dict.fromkeys(["glass", "windshield", "windscreen", "window"], "glass"),
    **dict.fromkeys(["regulator", "lifter"], "window_regulator"),
    **dict.fromkeys(["door", "tailgate", "liftgate", "hatch", "trunk"], "door"),
    **dict.fromkeys(["handle", "knob"], "handle"),
    **dict.fromkeys(["lock", "latch", "striker"], "lock"),
    **dict.fromkeys(["hinge"], "hinge"),
    **dict.fromkeys(["bumper"], "bumper"),
    **dict.fromkeys(["fender", "bonnet", "hood", "roof", "pillar", "panel", "sill", "apron", "wing", "quarter",
                     "crossmember", "beam", "reinforcement", "floor", "frame", "wall"], "body_panel"),
    **dict.fromkeys(["grille", "grill"], "grille"),
    **dict.fromkeys(["trim", "strip", "moulding", "molding", "garnish", "finisher", "spoiler", "skirt", "step",
                     "eyebrow", "decoration"], "trim"),
    **dict.fromkeys(["emblem", "badge", "logo", "nameplate", "lettering", "mark"], "emblem"),
    **dict.fromkeys(["seal", "gasket", "sealing", "weatherstrip", "ring", "sleeve", "grommet"], "seal"),
    **dict.fromkeys(["hose", "pipe", "tube", "duct", "line", "piping", "tubing", "nozzle"], "hose"),
    **dict.fromkeys(["muffler", "silencer", "catalyst", "converter", "resonator"], "exhaust"),
    **dict.fromkeys(["absorber", "strut", "damper", "dumper"], "shock"),
    **dict.fromkeys(["spring", "leaf"], "spring"),
    **dict.fromkeys(["arm", "lever", "fork", "wishbone"], "arm"),
    **dict.fromkeys(["rod", "link", "linkage", "stabilizer", "joint", "end", "guide"], "rod"),
    **dict.fromkeys(["hub", "knuckle"], "hub"),
    **dict.fromkeys(["wheel", "tyre", "tire", "rim"], "wheel"),
    **dict.fromkeys(["steering"], "steering"),
    **dict.fromkeys(["tank", "kettle", "reservoir", "bottle"], "tank"),
    **dict.fromkeys(["piston"], "piston"),
    **dict.fromkeys(["clutch"], "clutch"),
    **dict.fromkeys(["valve", "thermostat", "injector"], "valve"),
    **dict.fromkeys(["motor", "starter", "generator", "alternator", "actuator"], "motor"),
    **dict.fromkeys(["fan", "blower", "impeller"], "fan"),
    **dict.fromkeys(["radiator", "condenser", "evaporator", "intercooler", "core", "heater", "cooler"], "radiator"),
    **dict.fromkeys(["battery"], "battery"),
    **dict.fromkeys(["seat", "backrest", "headrest", "armrest"], "seat"),
    **dict.fromkeys(["airbag"], "airbag"),
    **dict.fromkeys(["pedal", "accelerator"], "pedal"),
    **dict.fromkeys(["engine"], "engine"),
    **dict.fromkeys(["bracket", "support", "mount", "mounting", "holder", "bush", "bushing", "cushion",
                     "insulator", "stay", "retainer"], "bracket"),
    **dict.fromkeys(["bolt", "nut", "screw", "clip", "clamp", "pin", "rivet", "washer", "stud", "fastener", "shim",
                     "spacer", "plug", "buckle", "hook", "snap"], "fastener"),
    **dict.fromkeys(["cover", "cap", "plate", "guard", "shield", "housing", "case", "lid", "mat", "visor",
                     "sunvisor", "baffle", "liner", "tray", "boot", "dust"], "cover"),
    **dict.fromkeys(["horn"], "horn"),
    **dict.fromkeys(["camera"], "camera"),
    **dict.fromkeys(["speaker", "tweeter", "loudspeaker"], "speaker"),
    **dict.fromkeys(["antenna"], "antenna"),
    **dict.fromkeys(["wiper", "blade"], "wiper"),
    **dict.fromkeys(["oil", "fluid", "coolant", "grease", "antifreeze", "liquid", "lubricant"], "fluid"),
    **dict.fromkeys(["tool", "tools", "wrench", "spanner", "puller", "jack", "kit"], "tools"),
    **dict.fromkeys(["mudguard", "mudflap", "ashtray", "board", "insulation"], "cover"),
    **dict.fromkeys(["instrument", "display", "screen", "multimedia", "radio", "gps", "clock", "monitor",
                     "navigation", "navigator", "dvr", "recorder"], "screen"),
    **dict.fromkeys(["host"], "radiator"),
    **dict.fromkeys(["key", "remote", "billet", "fob"], "key"),
    **dict.fromkeys(["turbocharger", "turbo", "supercharger"], "pump"),
    **dict.fromkeys(["manifold"], "hose"),
    **dict.fromkeys(["throttle", "tappet"], "valve"),
    **dict.fromkeys(["canister"], "tank"),
    **dict.fromkeys(["woofer", "subwoofer"], "speaker"),
    **dict.fromkeys(["transmission", "gearbox", "reducer", "mechanism"], "gear"),
    **dict.fromkeys(["chain"], "belt"),
    **dict.fromkeys(["label", "sticker"], "emblem"),
    **dict.fromkeys(["retroreflector", "reflector"], "lamp"),
    **dict.fromkeys(["deflector", "console"], "trim"),
    **dict.fromkeys(["bar", "track", "rail"], "rod"),
    **dict.fromkeys(["block", "stopper", "buffer"], "bracket"),
    **dict.fromkeys(["interface", "usb", "socket", "outlet", "charger"], "switch"),
    **dict.fromkeys(["bsm", "resistance", "resistor", "power"], "module"),
    **dict.fromkeys(["balancer"], "shaft"),
    **dict.fromkeys(["cage"], "bearing"),
    **dict.fromkeys(["cabin", "body"], "body_panel"),
    **dict.fromkeys(["flange"], "hub"),
}

# слова-«хвосты», которые не говорят, что это за деталь
NOISE = {"assy", "assembly", "asm", "assm", "assembled", "set", "lh", "rh", "left", "right", "front", "rear", "upper",
         "lower", "inner", "outer", "middle", "center", "centre", "l", "r", "a", "b", "c", "d", "i", "ii", "iii", "no",
         "new", "type", "with", "and", "of", "for", "the", "to", "in", "on", "at", "complete", "comp", "kit"}

# --- русский: первое слово (начало слова) → семейство; уточнения — по остальному названию ---
RU_FIRST = [
    ("подушка безопасн", "airbag"), ("подушк", "bracket"), ("ремень безопасн", "seatbelt"), ("ремень", "belt"),
    ("ремн", "belt"), ("фильтр", "air_filter"), ("масляный фильтр", "oil_filter"), ("воздушный фильтр", "air_filter"),
    ("топливный фильтр", "fuel_filter"), ("салонный фильтр", "air_filter"), ("диск", "brake_disc"),
    ("тормозной диск", "brake_disc"), ("кольц", "seal"), ("шарнир", "rod"),
    ("датчик", "sensor"), ("зонд", "sensor"), ("колодк", "brake_pad"), ("суппорт", "caliper"),
    ("подшипник", "bearing"), ("шестерн", "gear"), ("синхрониз", "gear"), ("звездочк", "gear"), ("звёздочк", "gear"),
    ("коленвал", "shaft"), ("распредвал", "shaft"), ("полуос", "shaft"), ("вал", "shaft"), ("свеч", "spark_plug"),
    ("ролик", "pulley"), ("натяжител", "pulley"), ("шкив", "pulley"), ("насос", "pump"), ("компрессор", "pump"),
    ("выключател", "switch"), ("переключател", "switch"), ("кнопк", "switch"),
    ("блок управлен", "module"), ("модуль", "module"), ("контроллер", "module"), ("реле", "module"),
    ("радар", "module"), ("предохранител", "module"), ("катушк", "module"),
    ("жгут", "harness"), ("провод", "harness"), ("трос", "harness"), ("кабел", "harness"),
    ("фара", "headlamp"), ("фары", "headlamp"), ("фонар", "lamp"), ("повторител", "lamp"), ("лампа", "lamp"),
    ("зеркал", "mirror"), ("стеклоподъ", "window_regulator"), ("стекл", "glass"), ("лобов", "glass"),
    ("двер", "door"), ("ручк", "handle"), ("рукоятк", "handle"), ("замок", "lock"), ("защёлк", "lock"),
    ("защелк", "lock"), ("личинк", "lock"), ("петл", "hinge"), ("бампер", "bumper"),
    ("крыло", "body_panel"), ("капот", "body_panel"), ("крыш", "body_panel"), ("стойка амортиз", "shock"),
    ("стойк", "body_panel"), ("панел", "body_panel"), ("порог", "body_panel"), ("лонжерон", "body_panel"),
    ("усилител", "body_panel"), ("балк", "body_panel"), ("решётк", "grille"), ("решетк", "grille"),
    ("молдинг", "trim"), ("накладк", "trim"), ("облицовк", "trim"), ("спойлер", "trim"), ("подножк", "trim"),
    ("эмблем", "emblem"), ("значок", "emblem"), ("надпис", "emblem"),
    ("сальник", "seal"), ("прокладк", "seal"), ("уплотнител", "seal"), ("уплотнен", "seal"),
    ("патрубок", "hose"), ("патрубк", "hose"), ("шланг", "hose"), ("трубк", "hose"), ("трубопровод", "hose"),
    ("труба глуш", "exhaust"), ("труба", "hose"), ("воздуховод", "hose"), ("форсунк", "valve"),
    ("глушител", "exhaust"), ("резонатор", "exhaust"), ("катализатор", "exhaust"),
    ("амортизатор", "shock"), ("пружин", "spring"), ("рессор", "spring"), ("лист рессор", "spring"),
    ("рычаг", "arm"), ("вилк", "arm"), ("тяга", "rod"), ("тяги", "rod"), ("наконечник", "rod"),
    ("стабилизатор", "rod"), ("шаров", "rod"), ("ступиц", "hub"), ("кулак", "hub"), ("цапф", "hub"),
    ("колес", "wheel"), ("колёс", "wheel"), ("шина", "wheel"), ("руль", "steering"), ("рулев", "steering"),
    ("бачок", "tank"), ("бак", "tank"), ("поршен", "piston"), ("поршн", "piston"), ("шатун", "piston"),
    ("сцеплен", "clutch"), ("корзин", "clutch"), ("клапан", "valve"), ("термостат", "valve"),
    ("электродвигател", "motor"), ("мотор", "motor"), ("стартер", "motor"), ("генератор", "motor"),
    ("привод", "motor"), ("вентилятор", "fan"), ("крыльчатк", "fan"),
    ("радиатор", "radiator"), ("конденсатор", "radiator"), ("испарител", "radiator"), ("интеркулер", "radiator"),
    ("аккумулятор", "battery"), ("сиден", "seat"), ("кресл", "seat"), ("подголовник", "seat"),
    ("подлокотник", "seat"), ("педал", "pedal"), ("двигател", "engine"), ("блок цилиндр", "engine"),
    ("головка блок", "engine"), ("кронштейн", "bracket"), ("опор", "bracket"), ("держател", "bracket"),
    ("втулк", "bracket"), ("сайлентблок", "bracket"), ("болт", "fastener"), ("гайк", "fastener"),
    ("винт", "fastener"), ("клипс", "fastener"), ("хомут", "fastener"), ("шпильк", "fastener"),
    ("штифт", "fastener"), ("шайб", "fastener"), ("пистон", "fastener"), ("заклёпк", "fastener"),
    ("заклепк", "fastener"), ("пробк", "fastener"), ("крюк", "fastener"), ("крышк", "cover"), ("заглушк", "cover"),
    ("пластин", "cover"), ("защит", "cover"), ("кожух", "cover"), ("корпус", "cover"), ("экран", "cover"),
    ("коврик", "cover"), ("козыр", "cover"), ("пыльник", "cover"), ("сигнал", "horn"), ("клаксон", "horn"),
    ("камер", "camera"), ("динамик", "speaker"), ("антенн", "antenna"), ("щётк", "wiper"), ("щетк", "wiper"),
    ("дворник", "wiper"), ("стеклоочист", "wiper"), ("масло", "fluid"), ("антифриз", "fluid"),
    ("жидкост", "fluid"), ("смазк", "fluid"), ("ключ", "tools"), ("съёмник", "tools"), ("съемник", "tools"),
    ("инструмент", "tools"), ("домкрат", "tools"), ("брызговик", "cover"), ("комбинация приборов", "screen"),
    ("приборн", "screen"), ("дисплей", "screen"), ("экран", "screen"), ("монитор", "screen"), ("магнитол", "screen"),
    ("часы", "screen"), ("ключ зажиг", "key"), ("смарт-ключ", "key"), ("брелок", "key"), ("пульт", "key"),
    ("турбокомпрессор", "pump"), ("турбин", "pump"), ("коллектор", "hose"), ("дроссел", "valve"),
    ("толкател", "valve"), ("адсорбер", "tank"), ("сабвуфер", "speaker"), ("коробк", "gear"), ("кпп", "gear"),
    ("редуктор", "gear"), ("цеп", "belt"), ("этикетк", "emblem"), ("наклейк", "emblem"), ("световозвращ", "lamp"),
    ("катафот", "lamp"), ("дефлектор", "trim"), ("консол", "trim"), ("торсион", "rod"), ("отбойник", "bracket"),
    ("розетк", "switch"), ("разъем", "switch"), ("разъём", "switch"), ("фланец", "hub"), ("кабин", "body_panel"),
]

# уточнения: семейство + слово в названии → другое семейство
REFINE = [
    ("air_filter", ("oil", "масл"), "oil_filter"), ("air_filter", ("fuel", "топлив"), "fuel_filter"),
    ("brake_disc", ("clutch", "сцепл"), "clutch"), ("brake_disc", ("wheel", "колес", "колёс"), "wheel"),
    ("brake_pad", ("seat", "сиден"), "seat"), ("bracket", ("безопасн", "airbag"), "airbag"),
    ("belt", ("seat", "safety", "безопасн"), "seatbelt"), ("seal", ("synchron", "синхрон"), "gear"),
    ("seal", ("piston", "поршн", "поршен"), "piston"), ("seal", ("snap", "stop", "стопор"), "fastener"),
    ("caliper", ("lock", "замк", "замок"), "lock"), ("caliper", ("engine", "двигател"), "engine"),
    ("fastener", ("spark", "зажиган"), "spark_plug"), ("hose", ("exhaust", "выхлоп", "глуш"), "exhaust"),
    ("wheel", ("steering", "рулев"), "steering"), ("glass", ("regulator", "подъ"), "window_regulator"),
    ("lamp", ("head", "фара"), "headlamp"), ("motor", ("wiper", "стеклоочист"), "motor"),
]

KEYWORDS = [  # запасной поиск по всему названию (порядок важен)
    (r"sensor|датчик", "sensor"), (r"filter|фильтр", "air_filter"), (r"bearing|подшипник", "bearing"),
    (r"lamp|light|фар|фонар", "lamp"), (r"mirror|зеркал", "mirror"), (r"door|двер", "door"),
    (r"bumper|бампер", "bumper"), (r"gear|шестерн", "gear"), (r"shaft|вал", "shaft"), (r"pump|насос", "pump"),
    (r"brake|тормоз", "brake_pad"), (r"seal|gasket|сальник|уплотн|прокладк", "seal"),
    (r"pipe|hose|tube|шланг|трубк|патруб", "hose"), (r"wire|harness|жгут|провод", "harness"),
    (r"engine|двигател", "engine"), (r"wheel|колес", "wheel"), (r"seat|сиден", "seat"),
    (r"bracket|кронштейн", "bracket"), (r"cover|крышк", "cover"),
]


def _tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z]+", (name or "").lower().replace("o-ring", "o ring"))
    return [w for w in words if w not in NOISE]


def _from_english(name: str) -> str | None:
    words = _tokens(name)
    for end in range(len(words), max(len(words) - 3, 0), -1):  # главное слово — последнее; хвост без смысла пропускаем
        if end >= 2 and f"{words[end - 2]} {words[end - 1]}" in HEAD2:
            return HEAD2[f"{words[end - 2]} {words[end - 1]}"]
        if words[end - 1] in HEAD1:
            return HEAD1[words[end - 1]]
    return None


def _from_russian(name: str) -> str | None:
    text = " ".join((name or "").lower().replace("ё", "е").split())
    for stem, key in sorted(RU_FIRST, key=lambda p: -len(p[0])):  # «стойка амортиз» раньше «стойк»
        if text.startswith(stem.replace("ё", "е")):
            return key
    return None


def picture_key(name_en: str | None, name_ru: str | None = None) -> str:
    """Семейство рисунка для детали: «oil_filter», «brake_pad», «door»… или «part», если не узнали."""
    text = f"{name_en or ''} {name_ru or ''}".lower()
    key = None
    if name_en and re.search(r"[a-z]", name_en.lower()):
        key = _from_english(name_en)
    if key is None:
        key = _from_russian(name_ru or "")
    if key is None:
        key = next((k for pattern, k in KEYWORDS if re.search(pattern, text)), None)
    if key is None:
        return DEFAULT
    for family, words, refined in REFINE:
        if key == family and any(w in text for w in words):
            return refined
    if key == "brake_pad" and not any(w in text for w in ("brake", "тормоз", "колодк")):
        return "cover"  # «pad» без тормозов — мягкая накладка, а не колодка
    return key
