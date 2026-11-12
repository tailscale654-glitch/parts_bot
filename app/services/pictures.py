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
    "control arm": "arm", "swing arm": "arm", "tie rod": "tie_rod", "ball joint": "tie_rod", "rod end": "tie_rod",
    "shock absorber": "shock", "wheel hub": "hub", "steering wheel": "steering", "steering gear": "steering",
    "steering column": "steering", "steering rack": "steering",
    "window regulator": "window_regulator", "glass regulator": "window_regulator",
    "wiper blade": "wiper", "wiper arm": "wiper", "wiper motor": "motor", "washer nozzle": "wiper",
    "air bag": "airbag", "fog lamp": "fog_lamp", "fog light": "fog_lamp", "head lamp": "headlamp", "tail lamp": "tail_lamp",
    "door glass": "door_glass", "piston ring": "piston_ring", "oil ring": "piston_ring", "air ring": "piston_ring",
    "connecting rod": "piston", "oil seal": "oil_seal", "o ring": "o_ring", "sealing ring": "o_ring",
    "synchronizer ring": "synchronizer", "snap ring": "snap_ring", "retaining ring": "snap_ring", "clip ring": "snap_ring",
    "drive shaft": "driveshaft", "half shaft": "driveshaft", "engine oil": "fluid", "brake fluid": "fluid",
    "water pump": "pump", "oil pump": "pump", "fuel pump": "pump", "washer pump": "pump",
    "expansion tank": "tank", "fuel tank": "tank", "washer tank": "tank", "washer kettle": "tank",
    "clutch disc": "clutch", "clutch disk": "clutch", "pressure plate": "clutch", "release bearing": "bearing",
    "shift lever": "shift_lever", "gear lever": "shift_lever", "shift knob": "shift_lever", "select lever": "shift_lever",
    "cylinder head": "engine", "cylinder block": "engine", "lock cylinder": "lock",
    "brake cylinder": "caliper", "master cylinder": "caliper", "wheel cylinder": "caliper", "slave cylinder": "caliper",
    "license plate": "cover", "number plate": "cover", "seat cushion": "seat", "engine cushion": "mount",
    "side step": "step", "rearview mirror": "mirror", "ignition coil": "ignition_coil",
    "throttle body": "throttle_body", "torsion bar": "rod", "stop block": "mount", "ball cage": "bearing",
    "smart key": "key", "remote key": "key", "timing chain": "belt", "clock spring": "module",
    # конкретные детали (подробные рисунки)
    "oxygen sensor": "oxygen_sensor", "lambda sensor": "oxygen_sensor", "abs sensor": "wheel_speed_sensor",
    "radar sensor": "parking_sensor", "parking sensor": "parking_sensor",
    "regulator switch": "window_switch", "window switch": "window_switch", "ignition switch": "ignition_switch",
    "combination switch": "stalk", "multifunction switch": "stalk",
    "brake tube": "brake_line", "brake hose": "brake_line", "brake pipe": "brake_line", "brake line": "brake_line",
    "steel tube": "brake_line", "air duct": "air_duct", "fuel rail": "fuel_rail", "universal joint": "universal_joint",
    "outer handle": "outer_handle", "inner handle": "inner_handle", "roof handle": "grab_handle",
    "grab handle": "grab_handle", "assist handle": "grab_handle", "wheel cover": "wheel_liner",
    "tow hook": "tow_hook", "pull hook": "tow_hook", "dust cover": "boot", "filler cap": "cap", "filler cover": "cap",
    "trim panel": "inner_trim", "instrument panel": "dashboard", "central console": "dashboard",
    "weather strip": "weatherstrip", "rubber strip": "weatherstrip", "sealing strip": "weatherstrip",
    "seal strip": "weatherstrip", "waterproof strip": "weatherstrip", "roof lamp": "interior_lamp",
    "reading lamp": "interior_lamp", "dome lamp": "interior_lamp", "room lamp": "interior_lamp",
    "turning lamp": "turn_signal", "turn lamp": "turn_signal", "side marker": "turn_signal",
    "wheel eyebrow": "wheel_arch", "bearing shell": "bearing_shell", "bearing bush": "bearing_shell",
    "needle bearing": "needle_bearing", "roller bearing": "tapered_bearing", "head gasket": "gasket",
    "shift fork": "shift_fork", "fork shaft": "shift_fork",
}

# --- английский: последнее слово ---
HEAD1 = {
    **dict.fromkeys(["filter", "strainer"], "air_filter"),
    **dict.fromkeys(["pad", "shoe"], "brake_pad"),
    **dict.fromkeys(["disc", "disk", "rotor", "drum"], "brake_disc"),
    **dict.fromkeys(["caliper", "cylinder"], "caliper"),
    **dict.fromkeys(["bearing"], "bearing"),
    **dict.fromkeys(["gear", "gears", "sprocket", "differential"], "gear"),
    **dict.fromkeys(["synchronizer", "synchroniser"], "synchronizer"),
    **dict.fromkeys(["shaft", "countershaft", "spindle"], "shaft"),
    **dict.fromkeys(["crankshaft"], "crankshaft"), **dict.fromkeys(["camshaft"], "camshaft"),
    **dict.fromkeys(["axle"], "axle"), **dict.fromkeys(["driveshaft", "propshaft"], "driveshaft"),
    **dict.fromkeys(["belt"], "belt"),
    **dict.fromkeys(["pulley", "tensioner", "idler", "roller"], "pulley"),
    **dict.fromkeys(["pump", "compressor"], "pump"),
    **dict.fromkeys(["sensor", "probe"], "sensor"),
    **dict.fromkeys(["switch", "button"], "switch"),
    **dict.fromkeys(["module", "unit", "amplifier", "inverter", "fuse", "coil", "receiver", "transmitter", "box"], "module"),
    **dict.fromkeys(["controller", "ecu", "ecm", "tcu", "bcm", "computer"], "ecu"),
    **dict.fromkeys(["relay"], "relay"), **dict.fromkeys(["radar"], "parking_sensor"),
    **dict.fromkeys(["harness", "wire", "wiring"], "harness"),
    **dict.fromkeys(["cable", "cord"], "cable"),
    **dict.fromkeys(["headlamp", "headlight"], "headlamp"),
    **dict.fromkeys(["lamp", "light", "lantern"], "lamp"),
    **dict.fromkeys(["indicator", "repeater"], "turn_signal"), **dict.fromkeys(["bulb"], "bulb"),
    **dict.fromkeys(["mirror"], "mirror"),
    **dict.fromkeys(["glass", "window"], "glass"), **dict.fromkeys(["windshield", "windscreen"], "windshield"),
    **dict.fromkeys(["regulator", "lifter"], "window_regulator"),
    **dict.fromkeys(["door", "tailgate", "liftgate", "hatch", "trunk"], "door"),
    **dict.fromkeys(["handle", "knob"], "handle"),
    **dict.fromkeys(["lock", "latch", "striker"], "lock"),
    **dict.fromkeys(["hinge"], "hinge"),
    **dict.fromkeys(["bumper"], "bumper"),
    **dict.fromkeys(["roof", "panel", "sill", "apron", "quarter", "floor", "frame", "wall"], "body_panel"),
    **dict.fromkeys(["fender", "wing"], "fender"), **dict.fromkeys(["bonnet", "hood"], "hood"),
    **dict.fromkeys(["pillar", "crossmember", "beam", "reinforcement"], "beam"),
    **dict.fromkeys(["grille", "grill"], "grille"),
    **dict.fromkeys(["trim", "strip", "moulding", "molding", "garnish", "finisher", "spoiler", "skirt", "decoration"], "trim"),
    **dict.fromkeys(["step"], "step"), **dict.fromkeys(["eyebrow", "arch"], "wheel_arch"),
    **dict.fromkeys(["emblem", "badge", "logo", "nameplate", "lettering", "mark"], "emblem"),
    **dict.fromkeys(["seal", "ring"], "seal"), **dict.fromkeys(["gasket"], "gasket"),
    **dict.fromkeys(["weatherstrip", "sealing"], "weatherstrip"), **dict.fromkeys(["sleeve", "grommet"], "bushing"),
    **dict.fromkeys(["hose", "pipe", "tube", "line", "piping", "tubing", "nozzle"], "hose"),
    **dict.fromkeys(["duct"], "air_duct"),
    **dict.fromkeys(["muffler", "silencer", "catalyst", "converter", "resonator"], "exhaust"),
    **dict.fromkeys(["absorber", "strut", "damper", "dumper"], "shock"),
    **dict.fromkeys(["spring", "leaf"], "spring"),
    **dict.fromkeys(["arm", "lever", "fork", "wishbone"], "arm"),
    **dict.fromkeys(["rod", "link", "linkage", "joint", "end", "guide"], "rod"),
    **dict.fromkeys(["stabilizer", "stabiliser"], "stabilizer"),
    **dict.fromkeys(["hub", "knuckle"], "hub"),
    **dict.fromkeys(["wheel", "tyre", "tire", "rim"], "wheel"),
    **dict.fromkeys(["steering"], "steering"),
    **dict.fromkeys(["tank", "kettle", "reservoir", "bottle"], "tank"),
    **dict.fromkeys(["piston"], "piston"),
    **dict.fromkeys(["clutch"], "clutch"),
    **dict.fromkeys(["valve"], "valve"), **dict.fromkeys(["thermostat"], "thermostat"),
    **dict.fromkeys(["injector"], "injector"),
    **dict.fromkeys(["motor", "actuator"], "motor"), **dict.fromkeys(["starter"], "starter"),
    **dict.fromkeys(["generator", "alternator"], "alternator"),
    **dict.fromkeys(["fan", "blower", "impeller"], "fan"),
    **dict.fromkeys(["radiator", "condenser", "evaporator", "intercooler", "core", "heater", "cooler"], "radiator"),
    **dict.fromkeys(["battery"], "battery"),
    **dict.fromkeys(["seat", "backrest", "headrest", "armrest"], "seat"),
    **dict.fromkeys(["airbag"], "airbag"),
    **dict.fromkeys(["pedal", "accelerator"], "pedal"),
    **dict.fromkeys(["engine"], "engine"),
    **dict.fromkeys(["bracket", "support", "holder", "stay", "retainer"], "bracket"),
    **dict.fromkeys(["mount", "mounting", "cushion", "insulator"], "mount"),
    **dict.fromkeys(["bush", "bushing"], "bushing"),
    **dict.fromkeys(["bolt", "screw", "stud"], "bolt"), **dict.fromkeys(["nut"], "nut"),
    **dict.fromkeys(["washer", "shim", "spacer"], "washer"), **dict.fromkeys(["pin"], "pin"),
    **dict.fromkeys(["plug"], "plug"), **dict.fromkeys(["hook"], "tow_hook"),
    **dict.fromkeys(["clip", "rivet", "snap"], "clip"), **dict.fromkeys(["clamp", "fastener", "buckle"], "fastener"),
    **dict.fromkeys(["cover", "plate", "guard", "mat", "visor", "sunvisor", "baffle", "tray"], "cover"),
    **dict.fromkeys(["cap", "lid"], "cap"), **dict.fromkeys(["housing", "case"], "housing"),
    **dict.fromkeys(["boot", "dust", "bellows"], "boot"), **dict.fromkeys(["liner"], "wheel_liner"),
    **dict.fromkeys(["shield"], "heat_shield"),
    **dict.fromkeys(["horn"], "horn"),
    **dict.fromkeys(["camera"], "camera"),
    **dict.fromkeys(["speaker", "tweeter", "loudspeaker"], "speaker"),
    **dict.fromkeys(["antenna"], "antenna"),
    **dict.fromkeys(["wiper", "blade"], "wiper"),
    **dict.fromkeys(["oil", "fluid", "coolant", "grease", "antifreeze", "liquid", "lubricant"], "fluid"),
    **dict.fromkeys(["tool", "tools", "wrench", "spanner", "puller", "jack", "kit"], "tools"),
    **dict.fromkeys(["ashtray", "board"], "cover"), **dict.fromkeys(["mudguard", "mudflap"], "wheel_liner"),
    **dict.fromkeys(["insulation"], "heat_shield"),
    **dict.fromkeys(["instrument", "display", "screen", "multimedia", "radio", "gps", "clock", "monitor",
                     "navigation", "navigator", "dvr", "recorder"], "screen"),
    **dict.fromkeys(["host"], "radiator"),
    **dict.fromkeys(["key", "remote", "billet", "fob"], "key"),
    **dict.fromkeys(["turbocharger", "turbo", "supercharger"], "pump"),
    **dict.fromkeys(["manifold"], "hose"),
    **dict.fromkeys(["tappet"], "valve"), **dict.fromkeys(["throttle"], "throttle_body"),
    **dict.fromkeys(["canister"], "tank"),
    **dict.fromkeys(["woofer", "subwoofer"], "speaker"),
    **dict.fromkeys(["transmission", "gearbox", "reducer"], "transmission"), **dict.fromkeys(["mechanism"], "gear"),
    **dict.fromkeys(["chain"], "belt"),
    **dict.fromkeys(["label", "sticker"], "emblem"),
    **dict.fromkeys(["retroreflector", "reflector"], "reflector"),
    **dict.fromkeys(["deflector"], "trim"), **dict.fromkeys(["console"], "dashboard"),
    **dict.fromkeys(["bar"], "rod"), **dict.fromkeys(["track", "rail"], "track"),
    **dict.fromkeys(["block", "stopper", "buffer"], "mount"),
    **dict.fromkeys(["interface", "usb", "socket", "outlet", "charger"], "usb_port"),
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
    ("подушка безопасн", "airbag"), ("подушк", "mount"), ("ремень безопасн", "seatbelt"), ("ремень", "belt"),
    ("ремн", "belt"), ("фильтр", "air_filter"), ("масляный фильтр", "oil_filter"), ("воздушный фильтр", "air_filter"),
    ("топливный фильтр", "fuel_filter"), ("салонный фильтр", "air_filter"), ("диск", "brake_disc"),
    ("тормозной диск", "brake_disc"), ("кольц", "seal"), ("кольцо уплотн", "o_ring"), ("уплотнительное кольц", "o_ring"), ("стопорн", "snap_ring"), ("поршнев", "piston_ring"), ("шарнир", "rod"),
    ("датчик", "sensor"), ("зонд", "sensor"), ("колодк", "brake_pad"), ("суппорт", "caliper"),
    ("подшипник", "bearing"), ("шестерн", "gear"), ("синхрониз", "synchronizer"), ("звездочк", "gear"), ("звёздочк", "gear"),
    ("коленвал", "crankshaft"), ("распредвал", "camshaft"), ("полуос", "driveshaft"), ("кардан", "driveshaft"), ("вилка переключ", "shift_fork"), ("вал", "shaft"), ("свеч", "spark_plug"),
    ("ролик", "pulley"), ("натяжител", "pulley"), ("шкив", "pulley"), ("насос", "pump"), ("компрессор", "pump"),
    ("выключател", "switch"), ("переключател", "switch"), ("кнопк", "switch"),
    ("блок управлен", "ecu"), ("эбу", "ecu"), ("модуль", "module"), ("контроллер", "ecu"), ("реле", "relay"),
    ("радар", "parking_sensor"), ("предохранител", "module"), ("катушка зажиган", "ignition_coil"), ("катушк", "module"),
    ("жгут", "harness"), ("провод", "harness"), ("трос", "cable"), ("кабел", "cable"),
    ("фара", "headlamp"), ("фары", "headlamp"), ("фонар", "lamp"), ("повторител", "turn_signal"), ("лампа", "bulb"), ("лампочк", "bulb"), ("плафон", "interior_lamp"), ("противотуман", "fog_lamp"),
    ("зеркал", "mirror"), ("стеклоподъ", "window_regulator"), ("стекл", "glass"), ("лобов", "windshield"),
    ("двер", "door"), ("ручк", "handle"), ("рукоятк", "handle"), ("замок", "lock"), ("защёлк", "lock"),
    ("защелк", "lock"), ("личинк", "lock"), ("петл", "hinge"), ("бампер", "bumper"),
    ("крыло", "fender"), ("капот", "hood"), ("крыш", "body_panel"), ("стойка амортиз", "shock"),
    ("стойк", "body_panel"), ("панел", "body_panel"), ("порог", "body_panel"), ("лонжерон", "beam"),
    ("усилител", "beam"), ("балк", "beam"), ("поперечин", "beam"), ("решётк", "grille"), ("решетк", "grille"),
    ("молдинг", "trim"), ("накладк", "trim"), ("облицовк", "trim"), ("спойлер", "trim"), ("подножк", "step"), ("арк", "wheel_arch"),
    ("эмблем", "emblem"), ("значок", "emblem"), ("надпис", "emblem"),
    ("сальник", "oil_seal"), ("прокладк", "gasket"), ("уплотнител", "weatherstrip"), ("уплотнен", "seal"),
    ("патрубок", "hose"), ("патрубк", "hose"), ("шланг", "hose"), ("трубк", "hose"), ("трубопровод", "hose"),
    ("труба глуш", "exhaust"), ("труба", "hose"), ("воздуховод", "air_duct"), ("форсунк", "injector"), ("топливная рампа", "fuel_rail"), ("рампа", "fuel_rail"),
    ("глушител", "exhaust"), ("резонатор", "exhaust"), ("катализатор", "exhaust"),
    ("амортизатор", "shock"), ("пружин", "spring"), ("рессор", "spring"), ("лист рессор", "spring"),
    ("рычаг", "arm"), ("вилк", "arm"), ("крестовин", "universal_joint"), ("тяга", "rod"), ("тяги", "rod"), ("наконечник", "rod"),
    ("стабилизатор", "stabilizer"), ("шаров", "rod"), ("ступиц", "hub"), ("кулак", "hub"), ("цапф", "hub"),
    ("колес", "wheel"), ("колёс", "wheel"), ("шина", "wheel"), ("руль", "steering"), ("рулев", "steering"),
    ("бачок", "tank"), ("бак", "tank"), ("поршен", "piston"), ("поршн", "piston"), ("шатун", "piston"),
    ("сцеплен", "clutch"), ("корзин", "clutch"), ("клапан", "valve"), ("термостат", "thermostat"),
    ("электродвигател", "motor"), ("мотор", "motor"), ("стартер", "starter"), ("генератор", "alternator"),
    ("привод", "motor"), ("вентилятор", "fan"), ("крыльчатк", "fan"),
    ("радиатор", "radiator"), ("конденсатор", "radiator"), ("испарител", "radiator"), ("интеркулер", "radiator"),
    ("аккумулятор", "battery"), ("сиден", "seat"), ("ступенк", "step"), ("кресл", "seat"), ("подголовник", "seat"),
    ("подлокотник", "seat"), ("педал", "pedal"), ("двигател", "engine"), ("блок цилиндр", "engine"),
    ("головка блок", "engine"), ("кронштейн", "bracket"), ("опора двигател", "mount"), ("опор", "bracket"), ("держател", "bracket"),
    ("втулк", "bushing"), ("сайлентблок", "bushing"), ("болт", "bolt"), ("гайк", "nut"),
    ("винт", "bolt"), ("клипс", "clip"), ("хомут", "fastener"), ("шпильк", "bolt"),
    ("штифт", "pin"), ("шплинт", "pin"), ("палец", "pin"), ("шайб", "washer"), ("пистон", "clip"), ("заклёпк", "clip"),
    ("заклепк", "clip"), ("пробк", "plug"), ("крюк", "tow_hook"), ("буксир", "tow_hook"), ("крышк", "cap"), ("заглушк", "plug"),
    ("пластин", "cover"), ("защит", "cover"), ("кожух", "housing"), ("корпус", "housing"), ("теплоизол", "heat_shield"), ("термоэкран", "heat_shield"), ("экран", "cover"),
    ("коврик", "cover"), ("козыр", "cover"), ("пыльник", "boot"), ("чехол", "boot"), ("гофр", "boot"), ("сигнал", "horn"), ("клаксон", "horn"),
    ("камер", "camera"), ("динамик", "speaker"), ("антенн", "antenna"), ("щётк", "wiper"), ("щетк", "wiper"),
    ("дворник", "wiper"), ("стеклоочист", "wiper"), ("масло", "fluid"), ("антифриз", "fluid"),
    ("жидкост", "fluid"), ("смазк", "fluid"), ("ключ", "tools"), ("съёмник", "tools"), ("съемник", "tools"),
    ("инструмент", "tools"), ("домкрат", "tools"), ("брызговик", "wheel_liner"), ("подкрылок", "wheel_liner"), ("локер", "wheel_liner"), ("комбинация приборов", "screen"),
    ("приборн", "screen"), ("дисплей", "screen"), ("экран", "screen"), ("монитор", "screen"), ("магнитол", "screen"),
    ("часы", "screen"), ("ключ зажиг", "key"), ("замок зажиган", "ignition_switch"), ("смарт-ключ", "key"), ("брелок", "key"), ("пульт", "key"),
    ("турбокомпрессор", "pump"), ("турбин", "pump"), ("коллектор", "hose"), ("дроссел", "throttle_body"),
    ("толкател", "valve"), ("адсорбер", "tank"), ("сабвуфер", "speaker"), ("коробк", "transmission"), ("кпп", "transmission"),
    ("редуктор", "gear"), ("цеп", "belt"), ("этикетк", "emblem"), ("наклейк", "emblem"), ("световозвращ", "reflector"),
    ("катафот", "reflector"), ("дефлектор", "trim"), ("консол", "dashboard"), ("торпед", "dashboard"), ("торсион", "stabilizer"), ("отбойник", "mount"),
    ("розетк", "usb_port"), ("разъем", "usb_port"), ("разъём", "usb_port"), ("фланец", "hub"), ("кабин", "body_panel"),
    ("вкладыш", "bearing_shell"), ("кислородн", "oxygen_sensor"), ("лямбда", "oxygen_sensor"),
    ("стоп-сигнал", "tail_lamp"), ("задний фонар", "tail_lamp"), ("порт usb", "usb_port"), ("usb", "usb_port"),
    ("щиток приборов", "dashboard"), ("панель приборов", "dashboard"), ("обшивк", "inner_trim"),
    ("уплотнитель двер", "weatherstrip"), ("сигнальн", "horn"),
]

# уточнения: семейство + слово в названии → другое семейство
REFINE = [
    ("air_filter", ("oil", "масл"), "oil_filter"), ("air_filter", ("fuel", "топлив"), "fuel_filter"),
    ("brake_disc", ("clutch", "сцепл"), "clutch"), ("brake_disc", ("wheel", "колес", "колёс"), "wheel"),
    ("brake_pad", ("seat", "сиден"), "seat"), ("mount", ("безопасн", "airbag"), "airbag"),
    ("belt", ("seat", "safety", "безопасн"), "seatbelt"), ("seal", ("synchron", "синхрон"), "synchronizer"),
    ("seal", ("piston", "поршн", "поршен"), "piston_ring"), ("seal", ("snap", "stop", "стопор", "circlip"), "snap_ring"),
    ("caliper", ("lock", "замк", "замок"), "lock"), ("caliper", ("engine", "двигател"), "engine"),
    ("plug", ("spark", "glow", "свеч"), "spark_plug"), ("hose", ("exhaust", "выхлоп", "глуш"), "exhaust"),
    ("wheel", ("steering", "рулев"), "steering"), ("glass", ("regulator", "подъ"), "window_regulator"),
    ("lamp", ("head", "фара"), "headlamp"), ("bulb", ("head", "фара"), "headlamp"), ("motor", ("wiper", "стеклоочист"), "motor"),
]

# конкретные детали внутри семейства: (семейство, regex по всему названию, рисунок); первое совпадение выигрывает
SPECIFIC = [
    ("sensor", r"oxygen|lambda|кислород|лямбда", "oxygen_sensor"),
    ("sensor", r"wheel speed|abs|скорости колес|скорости колёс|колеса|колёса", "wheel_speed_sensor"),
    ("sensor", r"radar|parking|reverse|парков|заднего хода", "parking_sensor"),
    ("switch", r"window|glass regulator|lifter|стеклоподъ", "window_switch"),
    ("switch", r"combination|multifunction|multi-function|подрулев|комбинирован", "stalk"),
    ("switch", r"ignition|зажиган", "ignition_switch"),
    ("switch", r"usb|socket|outlet|charger|розетк|разъ[её]м", "usb_port"),
    ("lamp", r"roof|reading|cab |dome|room|interior|салон|плафон|чтени", "interior_lamp"),
    ("lamp", r"\bfog|противотуман", "fog_lamp"),
    ("lamp", r"turn|repeater|indicator|side marker|повторит|поворот", "turn_signal"),
    ("lamp", r"tail|rear comb|rear lamp|stop lamp|brake lamp|задн|стоп", "tail_lamp"),
    ("handle", r"outer|outside|exterior|наружн", "outer_handle"),
    ("handle", r"inner|inside|interior|внутрен", "inner_handle"),
    ("handle", r"roof|grab|assist|потолоч", "grab_handle"),
    ("handle", r"shift|select|gear|кпп|переключ", "shift_lever"),
    ("hose", r"brake|clutch|тормоз|сцеплен", "brake_line"),
    ("hose", r"intake|air inlet|air outlet|воздух", "air_duct"),
    ("hose", r"fuel rail|топливная рампа", "fuel_rail"),
    ("bearing", r"shell|вкладыш|main bearing|connecting rod bearing|thrust bearing", "bearing_shell"),
    ("bearing", r"needle|игольч", "needle_bearing"),
    ("bearing", r"taper|conical|конич|roller|ролик", "tapered_bearing"),
    ("bracket", r"main bearing|connecting rod bearing|вкладыш", "bearing_shell"),
    ("trim", r"rubber|weather|seal|waterproof|уплотн", "weatherstrip"),
    ("trim", r"wheel arch|eyebrow|арк", "wheel_arch"),
    ("trim", r"door trim|trim panel|inner trim|interior trim|обшивк", "inner_trim"),
    ("body_panel", r"inner trim|interior trim|обшивк", "inner_trim"),
    ("glass", r"windshield|windscreen|лобов", "windshield"),
    ("glass", r"triangle|quarter|vent|треуг|форточк", "quarter_window"),
    ("glass", r"door|двер", "door_glass"),
    ("rod", r"universal|cardan|крестовин|кардан", "universal_joint"),
    ("rod", r"tie rod|ball joint|steering|рулев|шаров", "tie_rod"),
    ("rod", r"stabilizer|stabiliser|anti-roll|стабилизатор", "stabilizer"),
    ("harness", r"pull|cable|cord|трос", "cable"),
    ("tow_hook", r"lock|замк|замок", "lock"),
    ("lock", r"safety belt|seat belt|seatbelt|buckle|ремн|ремен", "seatbelt"),
    ("lock", r"ignition|зажиган", "ignition_switch"),
    ("turn_signal", r"anti-theft|противоугон", "module"),
    ("gear", r"lock|замк", "lock"),
    ("gear", r"pedal|педал", "pedal"),
    ("gear", r"wiper|стеклоочист", "wiper"),
    ("gear", r"shift control|shift gate|переключ", "shift_lever"),
    ("gear", r"synchron|синхрон", "synchronizer"),
    ("module", r"relay|реле", "relay"),
    ("module", r"hub unit|ступиц", "hub"),
    ("module", r"oil filter", "oil_filter"),
    ("module", r"intercooler|radiator|радиатор", "radiator"),
    ("module", r"antenna|антенн", "antenna"),
    ("module", r"glove box|бардач", "dashboard"),
    ("module", r"warning triangle|знак аварий", "tools"),
    ("module", r"support box|кронштейн", "bracket"),
    ("module", r"control unit|controller|\becu\b|\becm\b|\btcu\b|\bbcm\b|блок управлен|эбу", "ecu"),
    ("module", r"ignition coil|катушка зажиган", "ignition_coil"),
    ("cover", r"wheel|mudguard|mudflap|fender liner|подкрыл|брызгов", "wheel_liner"),
    ("cover", r"heat|thermal|insulation|exhaust|теплоизол|шумоизол|термо", "heat_shield"),
    ("cover", r"driven plate|friction plate|clutch|сцеплен", "clutch"),
    ("cover", r"thrust plate|упорн", "washer"),
    ("cover", r"mounting plate|fixing plate|support plate|backing plate|lifting lug|кронштейн", "bracket"),
    ("cover", r"pillar.*guard|guard plate.*gray|doorsill guard|обшивк", "inner_trim"),
    ("cover", r"inner plate|outer plate|side plate|cabin plate|reinforc|панел", "body_panel"),
    ("cover", r"dust|boot|bellows|пыльник|гофр", "boot"),
    ("cover", r"filler|fuel tank cap|oil cap|горлов", "cap"),
    ("shaft", r"crank|коленвал|коленчат", "crankshaft"),
    ("shaft", r"cam|распредел", "camshaft"),
    ("shaft", r"drive shaft|half shaft|propeller|cardan|полуос|кардан|привод", "driveshaft"),
    ("shaft", r"fork|вилк", "shift_fork"),
    ("valve", r"thermostat|термостат", "thermostat"),
    ("valve", r"injector|форсунк", "injector"),
    ("valve", r"throttle|дроссел", "throttle_body"),
    ("motor", r"starter|стартер", "starter"),
    ("motor", r"alternator|generator|генератор", "alternator"),
    ("piston", r"piston ring|поршнев.*кольц|кольц.*поршн", "piston_ring"),
    ("seal", r"gear ring|tone ring|flywheel|зубчат|венец", "gear"),
    ("seal", r"compression|компрессион", "piston_ring"),
    ("seal", r"clamp ring|snap|стопорн", "snap_ring"),
    ("seal", r"o ring|o-ring|круглого сечения", "o_ring"),
    ("seal", r"oil seal|сальник", "oil_seal"),
    ("seal", r"gasket|прокладк", "gasket"),
    ("bracket", r"motor|мотор", "motor"),
    ("bracket", r"pump|насос", "pump"),
    ("bracket", r"door glass|window glass|стекло двер", "door_glass"),
    ("bracket", r"engine .*support|shock absorber upper support|suspension connecting|опора двигат", "mount"),
    ("body_panel", r"\block\b|замк|замок", "lock"),
    ("body_panel", r"bumper|бампер", "bumper"),
    ("body_panel", r"shock absorber|амортиз", "shock"),
    ("body_panel", r"throttle|дроссел", "throttle_body"),
    ("body_panel", r"filler cover|лючок", "cap"),
    ("body_panel", r"fuel tank|canister|адсорбер", "tank"),
    ("body_panel", r"instrument panel|dashboard|торпед|приборн", "dashboard"),
    ("body_panel", r"pedal|педал", "pedal"),
    ("body_panel", r"switch panel|блок кнопок", "window_switch"),
    ("body_panel", r"sliding window|сдвижн.*окн|форточк", "glass"),
    ("hose", r"steel pipe|steel tube", "brake_line"),
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
    name = (name or "").lower().replace("o-ring", "o ring")
    bare = re.sub(r"\([^)]*(\)|$)", " ", name)  # «gasket(oil drain plug)» — главное слово gasket
    words = re.findall(r"[a-z]+", bare if re.search(r"[a-z]", bare) else name)
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
            key = refined
            break
    if key == "brake_pad" and not any(w in text for w in ("brake", "тормоз", "колодк")):
        key = "cover"  # «pad» без тормозов — мягкая накладка, а не колодка
    for family, pattern, specific in SPECIFIC:
        if key == family and re.search(pattern, text):
            return specific
    return key
