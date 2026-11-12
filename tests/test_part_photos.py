"""Фото деталей из электронного каталога JAC: архив из браузера → панель → бот, витрина и синхронизация."""
import io
import json
import zipfile
from types import SimpleNamespace

from aiogram.types import BufferedInputFile
from PIL import Image
from sqlalchemy import func, select

from app.database.models import EpcImage, EpcPhoto, Part, User
from app.handlers.catalog import card_view
from app.services import part_overrides, part_photos
from tests.test_offers_cart import db  # noqa: F401
from tests.test_panel import csrf_of, env, login  # noqa: F401
from tests.test_preorder import factory, sync  # noqa: F401
from tests.test_sync import row

MD5_A, MD5_B = "a" * 32, "b" * 32


def png(color, size=(600, 440), alpha=False) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", size, color)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def archive(parts: dict[str, str], images: dict[str, bytes], extra: dict[str, bytes] | None = None,
            index: bool = True, kind: str | None = None) -> bytes:
    """Как собирает браузер: index.json + img/<md5>.jpg. kind="jac-zap" — фото своего магазина."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        if index:
            z.writestr("index.json", json.dumps({"source": "JAC EPC", **({"kind": kind} if kind else {}), "parts": [
                {"pn": pn, "img": md5, "en": f"PART {pn}"} for pn, md5 in parts.items()]}))
        for md5, data in images.items():
            z.writestr(f"img/{md5}.jpg", data)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return out.getvalue()


async def upload(client, data: bytes, name="jac-epc-photos.zip"):
    token = await csrf_of(client, "/photos")
    return await client.post("/photos", data={"csrf": token}, files={"file": (name, data, "application/zip")})


async def test_photos_page_upload_and_bot(env):  # noqa: F811
    await login(env.client, *env.creds["admin"])
    page = await env.client.get("/photos")
    assert page.status_code == 200 and "Артикулов в боте" in page.text and "🖼 Фото деталей" in page.text
    assert "101001" in (await env.client.get("/photos/needed.txt")).text  # у масляного фильтра фото ещё нет

    zip_bytes = archive({"101001": MD5_A, "999999": MD5_B}, {MD5_A: png((255, 0, 0, 0), alpha=True), MD5_B: png("blue")},
                        extra={"../evil.sh": b"rm -rf /", "img/" + "c" * 32 + ".jpg": b"not an image"})
    r = await upload(env.client, zip_bytes)
    assert "Загружено из каталога JAC:" in r.text and "картинок <b>2</b> (новых 2), артикулов <b>2</b>" in r.text
    assert "не картинка" in r.text  # битый файл пропущен, остальные приняты
    part = await env.db.get(Part, 1)
    await env.db.refresh(part)
    assert part.photo == f"/media/parts/{MD5_A}.jpg"
    assert await env.db.scalar(select(func.count()).select_from(EpcImage)) == 2  # «evil.sh» и битая картинка не попали

    photo = await env.client.get(part.photo)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(photo.content))
    assert img.format == "JPEG" and img.size == (600, 440) and img.getpixel((10, 10))[0] > 240  # прозрачное → белое
    assert (await env.client.get("/media/parts/" + "f" * 32 + ".jpg")).status_code == 404
    assert f'src="/media/parts/{MD5_A}.jpg"' in (await env.client.get("/catalog/1")).text  # превью в карточке детали

    again = await upload(env.client, zip_bytes)  # тот же архив ещё раз — ничего не задвоится
    assert "(новых 0)" in again.text and await env.db.scalar(select(func.count()).select_from(EpcPhoto)) == 2
    assert "Нужен архив .zip" in (await upload(env.client, b"x", name="photos.xlsx")).text
    assert "Это не ZIP-архив" in (await upload(env.client, b"not a zip")).text
    assert "нет index.json" in (await upload(env.client, archive({}, {MD5_A: png("red")}, index=False))).text

    # бот: карточка с фото из базы, второй раз — file_id Telegram, картинка заново не загружается
    user = await env.db.get(User, 1)
    _, _, tg = await card_view(part, user, env.db, page=1)
    assert isinstance(tg.media, BufferedInputFile) and tg.key == part.photo
    tg.sent(SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="FILE-ID")]))
    _, _, tg = await card_view(part, user, env.db, page=1)
    assert tg.media == "FILE-ID"

    # своё фото из панели главнее; сбросили правку — снова фото из каталога JAC
    await part_overrides.save(env.db, part, models=[], node_ru=None, hidden=False, photo="https://example.com/own.jpg",
                              description_ru=None, description_uz=None, by_id=None)
    await env.db.commit()
    await upload(env.client, zip_bytes)
    await env.db.refresh(part)
    assert part.photo == "https://example.com/own.jpg"
    assert await part_overrides.reset(env.db, part)
    await env.db.commit()
    await env.db.refresh(part)
    assert part.photo == f"/media/parts/{MD5_A}.jpg"

    await login(env.client, *env.creds["operator"])  # у оператора нет права загружать
    assert (await env.client.get("/photos")).status_code == 403


async def test_sync_gives_library_photo_to_new_parts(factory):  # noqa: F811
    async with factory() as s:
        s.add(EpcImage(md5=MD5_A, data=part_photos.to_jpeg(png("green"))))
        s.add(EpcPhoto(key="5206100P3010", part_number="5206100P3010", image=MD5_A, name_en="FRONT WINDSHIELD"))
        await s.commit()
    await sync(factory, [row(1, "5206100P3010", "FRONT WINDSHIELD", "OOO «China Group»", model="T8-P30BF"),
                         row(2, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «China Group»", model="M4")])
    async with factory() as s:
        photos = dict((await s.execute(select(Part.part_number, Part.photo))).all())
    assert photos == {"5206100P3010": f"/media/parts/{MD5_A}.jpg", "1017100GD050": None}
    async with factory() as s:
        assert await part_photos.needed_numbers(s) == ["1017100GD050"]
        assert (await part_photos.summary(s))["epc"] == 1


def test_md5_of_rejects_foreign_links():
    assert part_photos.md5_of(f"/media/parts/{MD5_A}.jpg") == MD5_A
    for bad in ("https://example.com/a.jpg", "/media/parts/../../etc/passwd", "/media/parts/abc.jpg", None, ""):
        assert part_photos.md5_of(bad) is None


async def test_shop_photo_wins_over_jac_drawing(factory):  # noqa: F811
    """Фото магазина jac-zap.ru главнее рисунка каталога JAC — в каком бы порядке ни загружали архивы."""
    await sync(factory, [row(2, "1017100GD050", "ENGINE OIL FILTER ASSY.", "OOO «China Group»", model="M4")])
    epc = archive({"1017100GD050": MD5_A, "5206100P3010": MD5_A}, {MD5_A: png("gray")})
    shop = archive({"1017100GD050": MD5_B}, {MD5_B: png("white")}, kind="jac-zap")
    async with factory() as s:
        first = await part_photos.import_archive(s, io.BytesIO(epc))
        assert first.source == "epc" and first.parts == 1
        second = await part_photos.import_archive(s, io.BytesIO(shop))
        assert second.source == "jac-zap" and second.parts == 1  # рисунок JAC заменён настоящим фото
        again = await part_photos.import_archive(s, io.BytesIO(epc))  # каталог JAC ещё раз — фото магазина остаётся
        assert again.kept == 1 and again.numbers == 1 and again.parts == 0
        assert (await s.scalar(select(Part.photo))) == f"/media/parts/{MD5_B}.jpg"
        summary = await part_photos.summary(s)
        assert summary["library_shop"] == 1 and summary["library_epc"] == 1
