"""Фото деталей из электронного каталога JAC (EPC, uapp.jac.com.cn:4484).

Как попадают в бот:
  1. В браузере, где выполнен вход в каталог JAC, собирается архив ZIP: index.json (артикул → картинка)
     и картинки img/<md5>.jpg (имя — как в каталоге JAC).
  2. Администратор загружает архив в веб-панели: «🖼 Фото деталей».
  3. Здесь картинки проверяются и пережимаются (JPEG до 800 px), сохраняются в базу (epc_images),
     артикулы связываются с картинками (epc_photos), и фото сразу ставится деталям без своего фото.
     Новые детали из CarSale получат фото при ближайшей синхронизации (excel_import.apply_import).

У детали в поле photo — ссылка «/media/parts/<md5>.jpg»: витрина и панель отдают картинку из базы,
бот отправляет её файлом и запоминает file_id Telegram — второй раз картинка уже не загружается.
Своё фото из панели (ссылка в «Каталог → деталь») главнее фото из каталога JAC.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EpcImage, EpcPhoto, Part, PartOverride
from app.services.part_catalog import part_key

logger = logging.getLogger(__name__)

URL_PREFIX = "/media/parts/"
NAME_RE = re.compile(r"([0-9a-f]{32})\.jpg")
ARCHIVE_IMAGE_RE = re.compile(r"img/([0-9a-f]{32})\.(?:jpg|jpeg|png)")
MAX_ZIP_MB = 400  # 3–10 тысяч фото по 10–30 КБ — 50–250 МБ
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_FILES = 60_000
MAX_SIDE = 800  # картинки каталога 600×440 — не увеличиваем, огромные уменьшаем


def url_for(md5: str) -> str:
    return f"{URL_PREFIX}{md5}.jpg"


def md5_of(photo: str | None) -> str | None:
    """«/media/parts/<md5>.jpg» → md5; своя ссылка из панели или битое имя → None."""
    if not photo or not photo.startswith(URL_PREFIX):
        return None
    m = NAME_RE.fullmatch(photo[len(URL_PREFIX):])
    return m.group(1) if m else None


async def image_bytes(session: AsyncSession, md5: str) -> bytes | None:
    return await session.scalar(select(EpcImage.data).where(EpcImage.md5 == md5))


@dataclass
class PhotoImport:
    images: int = 0  # картинок принято (новых и тех, что уже были)
    new_images: int = 0
    numbers: int = 0  # артикулов связано с картинками
    parts: int = 0  # деталей в боте получили фото
    bad: list[str] = field(default_factory=list)  # что пропустили и почему (для панели)


def to_jpeg(data: bytes) -> bytes:
    """Проверить картинку и пережать в JPEG на белом фоне (заодно отбрасываются метаданные и «сюрпризы» в файле)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 30_000_000
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        if img.mode in ("RGBA", "LA", "P", "PA"):
            rgba = img.convert("RGBA")
            out = Image.new("RGB", rgba.size, (255, 255, 255))
            out.paste(rgba, mask=rgba.getchannel("A"))
        else:
            out = img.convert("RGB")
    out.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue()


def open_archive(fileobj) -> tuple[zipfile.ZipFile, dict[str, dict], list[zipfile.ZipInfo]]:
    """ZIP → (архив, {артикул: {"img", "en"}}, картинки в архиве). Чужие файлы в архиве не трогаем."""
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise ValueError("Это не ZIP-архив. Загрузите файл jac-epc-photos….zip, который скачал браузер.")
    infos = archive.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError(f"В архиве слишком много файлов ({len(infos)}).")
    if sum(i.file_size for i in infos) > MAX_ZIP_MB * 2 * 1024 * 1024:
        raise ValueError("Архив после распаковки слишком большой.")
    try:
        index = json.loads(archive.read("index.json"))
    except KeyError:
        raise ValueError("В архиве нет index.json — это не выгрузка фото из каталога JAC.")
    except ValueError:
        raise ValueError("index.json в архиве повреждён.")
    numbers: dict[str, dict] = {}
    for item in index.get("parts", []) if isinstance(index, dict) else []:
        if not isinstance(item, dict):
            continue
        pn, img = str(item.get("pn") or "").strip()[:64], str(item.get("img") or "").strip().lower()
        if pn and re.fullmatch(r"[0-9a-f]{32}", img):
            numbers[pn] = {"img": img, "en": (str(item.get("en") or "").strip()[:255] or None)}
    if not numbers:
        raise ValueError("В index.json нет ни одного артикула с картинкой.")
    return archive, numbers, [i for i in infos if ARCHIVE_IMAGE_RE.fullmatch(i.filename)]


def convert(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> tuple[dict[str, bytes], list[str]]:
    """Пачка картинок из архива → {md5: JPEG}, замечания. Тяжёлая работа — вызывать в отдельном потоке."""
    images: dict[str, bytes] = {}
    notes: list[str] = []
    for info in infos:
        md5 = ARCHIVE_IMAGE_RE.fullmatch(info.filename).group(1)
        if info.file_size > MAX_IMAGE_BYTES:
            notes.append(f"{info.filename}: файл больше 8 МБ — пропущен")
            continue
        try:
            images[md5] = to_jpeg(archive.read(info))
        except Exception as e:  # noqa: BLE001 — битая картинка не должна ломать весь архив
            notes.append(f"{info.filename}: не картинка ({type(e).__name__})")
    return images, notes


BATCH = 300  # картинок за раз: в памяти не больше ~10 МБ, сколько бы ни было в архиве


async def import_archive(session: AsyncSession, fileobj) -> PhotoImport:
    """Загрузка архива из панели: сохранить картинки, связать с артикулами, поставить фото деталям."""
    archive, numbers, infos = open_archive(fileobj)
    result = PhotoImport()
    with archive:
        known = set(await session.scalars(select(EpcImage.md5)))
        todo, seen = [], set()
        for info in infos:
            md5 = ARCHIVE_IMAGE_RE.fullmatch(info.filename).group(1)
            if md5 not in known and md5 not in seen:  # картинка уже есть в базе — второй раз не сохраняем
                seen.add(md5)
                todo.append(info)
        for start in range(0, len(todo), BATCH):
            images, notes = await asyncio.to_thread(convert, archive, todo[start:start + BATCH])
            result.bad += notes
            rows = [EpcImage(md5=md5, data=data) for md5, data in images.items()]
            session.add_all(rows)
            await session.flush()
            for r in rows:
                session.expunge(r)  # уже в базе (транзакция) — байты картинок в памяти больше не держим
            known |= set(images)
            result.new_images += len(images)
    result.images = len({i["img"] for i in numbers.values()} & known)

    existing = {p.key: p for p in await session.scalars(select(EpcPhoto))}
    for pn, info in numbers.items():
        if info["img"] not in known:
            continue  # картинки нет ни в архиве, ни в базе
        key = part_key(pn)
        row = existing.get(key)
        if row is None:
            row = existing[key] = EpcPhoto(key=key, part_number=pn, image=info["img"])
            session.add(row)
        row.image, row.name_en = info["img"], info["en"]
        result.numbers += 1
    await session.flush()
    result.parts = await apply_to_parts(session)
    await session.commit()
    logger.info("EPC photos imported: %s images (%s new), %s numbers, %s parts updated, %s skipped",
                result.images, result.new_images, result.numbers, result.parts, len(result.bad))
    return result


async def urls_by_key(session: AsyncSession) -> dict[str, str]:
    """{артикул: ссылка на фото из каталога JAC}."""
    return {key: url_for(md5) for key, md5 in (await session.execute(select(EpcPhoto.key, EpcPhoto.image))).all()}


async def apply_to_parts(session: AsyncSession) -> int:
    """Поставить фото из каталога JAC деталям, у которых нет своего фото из панели. → сколько деталей изменилось."""
    urls = await urls_by_key(session)
    own = set(await session.scalars(select(PartOverride.key).where(PartOverride.photo.is_not(None))))
    changed = 0
    for part in (await session.scalars(select(Part))).unique():
        key = part_key(part.part_number)
        url = urls.get(key)
        if key in own or not url or part.photo == url:
            continue
        if part.photo and not part.photo.startswith(URL_PREFIX):
            continue  # ссылка, поставленная раньше вручную, — не трогаем
        part.photo = url
        changed += 1
    return changed


async def needed_numbers(session: AsyncSession) -> list[str]:
    """Артикулы деталей в боте, у которых ещё нет фото, — для выгрузки из каталога JAC."""
    rows = await session.scalars(select(Part.part_number).where(Part.active.is_(True), Part.photo.is_(None)))
    return sorted({n.strip() for n in rows if n and n.strip()})


async def summary(session: AsyncSession) -> dict[str, int]:
    """Для страницы панели: сколько артикулов в боте, у скольких фото из каталога JAC, своё, без фото."""
    numbers: dict[str, str | None] = {}
    for number, photo in (await session.execute(select(Part.part_number, Part.photo).where(Part.active.is_(True)))).all():
        key = part_key(number)
        numbers[key] = numbers.get(key) or photo
    epc = sum(1 for p in numbers.values() if p and p.startswith(URL_PREFIX))
    own = sum(1 for p in numbers.values() if p and not p.startswith(URL_PREFIX))
    return {"total": len(numbers), "epc": epc, "own": own, "missing": len(numbers) - epc - own,
            "library": await session.scalar(select(func.count()).select_from(EpcPhoto)) or 0,
            "images": await session.scalar(select(func.count()).select_from(EpcImage)) or 0}


# ---------- бот: отправка фото и память file_id ----------

_file_ids: dict[str, str] = {}


async def telegram_photo(session: AsyncSession, photo: str | None):
    """Что передать в answer_photo: file_id (уже отправляли), картинку из базы или чужую ссылку как есть.
    None — без фото (картинки нет)."""
    if not photo:
        return None
    md5 = md5_of(photo)
    if md5 is None:
        return None if photo.startswith(URL_PREFIX) else photo
    if photo in _file_ids:
        return _file_ids[photo]
    data = await image_bytes(session, md5)
    if data is None:
        return None
    from aiogram.types import BufferedInputFile

    return BufferedInputFile(data, filename=f"{md5}.jpg")


def remember(photo: str | None, sent) -> None:
    """После отправки: запомнить file_id, чтобы не загружать картинку в Telegram снова."""
    if photo and photo.startswith(URL_PREFIX) and getattr(sent, "photo", None):
        _file_ids[photo] = sent.photo[-1].file_id


@dataclass
class TgPhoto:
    """Фото для карточки в боте: key — что записано у детали, media — что отдать Telegram."""
    key: str
    media: object

    def sent(self, message) -> None:
        remember(self.key, message)


async def for_telegram(session: AsyncSession, photo: str | None) -> TgPhoto | None:
    media = await telegram_photo(session, photo)
    return TgPhoto(photo, media) if media is not None else None
