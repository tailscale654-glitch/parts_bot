"""Правка детали администратором в панели: сразу в боте и сохраняется при синхронизации."""
from sqlalchemy import select

from app.database.models import BotSetting, Part, PartOverride
from app.services.excel_import import validate_any
from app.services.part_catalog import SYNC_REQUEST_KEY
from app.services.part_overrides import Override, model_triple
from app.sync.carsale import write_xlsx
from tests.test_offers_cart import db  # noqa: F401
from tests.test_panel import env, login  # noqa: F401
from tests.test_panel_w3 import post
from tests.test_sync import row, snapshot


async def test_admin_edits_part(env):  # noqa: F811
    await login(env.client, *env.creds["admin"])
    page = (await env.client.get("/catalog/1")).text
    assert "Изменить деталь" in page and "JAC M4 Luxe" in page
    r = await post(env.client, "/catalog/1/edit", {
        "models": ["JAC M3", "JAC T9"], "node_ru": "Кузов", "description_ru": "С 2022 года",
        "photo": "https://example.com/p.jpg"}, "/catalog/1")
    assert r.status_code == 303 and "flash" in r.headers["location"]
    part = await env.db.get(Part, 1)
    await env.db.refresh(part)
    assert part.node.name_ru == "Кузов" and part.description_ru == "С 2022 года" and part.photo.endswith("p.jpg")
    item = await env.db.scalar(select(PartOverride))
    assert item.model_list == ["JAC M3", "JAC T9"]
    assert (await env.db.get(BotSetting, SYNC_REQUEST_KEY)).value
    assert part.part_number in (await env.client.get("/catalog?show=edited")).text

    r = await post(env.client, "/catalog/1/edit", {"hidden": "1", "photo": "ftp://x"}, "/catalog/1")
    assert "%E2%9A%A0" in r.headers["location"]  # ⚠️ плохая ссылка на фото — ничего не сохранили
    await post(env.client, "/catalog/1/edit", {"hidden": "1"}, "/catalog/1")
    await env.db.refresh(part)
    assert part.active is False and "скрыта администратором" in (await env.client.get("/catalog/1")).text

    await post(env.client, "/catalog/1/edit", {"reset": "1"}, "/catalog/1")
    assert await env.db.scalar(select(PartOverride)) is None

    await login(env.client, *env.creds["operator"])
    assert "Изменить деталь" not in (await env.client.get("/catalog/1")).text
    assert (await post(env.client, "/catalog/1/edit", {"hidden": "1"}, "/catalog/1")).status_code == 403


def test_override_wins_over_carsale(tmp_path):
    from app.database.models import Region

    path = write_xlsx(snapshot([row(3, "X1", "OIL FILTER", "OOO «ASIAMOTOR»", model="T8-P30BF", typ="A"),
                                row(2, "X2", "BELT", "OOO «ASIAMOTOR»")]), tmp_path / "w.xlsx")
    overrides = {"X1": Override(models=[model_triple("JAC M3"), model_triple("Прочее")],
                                node=("Кузов", "Body", "Kuzov"), photo="https://e/p.jpg",
                                description={"ru": "Описание", "en": None, "uz": "Tavsif"}),
                 "X2": Override(hidden=True)}
    rows, errors, warnings, _ = validate_any(path, [Region(id=1, code="tashkent_city", name_ru="Т")],
                                             overrides=overrides)
    assert not errors and {r.part_number for r in rows} == {"X1"}
    assert sorted(r.model["ru"] for r in rows) == ["JAC M3", "Прочее"]
    assert rows[0].node["ru"] == "Кузов" and rows[0].photo == "https://e/p.jpg" and rows[0].description["uz"] == "Tavsif"
    assert any(w.key == "warn_admin_hidden" for w in warnings)
