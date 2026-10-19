"""Чат с клиентами: сообщения клиента боту → раздел «Чат» панели → ответ уходит клиенту в Telegram."""
import io
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import Region, SupportChat, SupportMessage, User
from app.handlers import support as support_handlers
from app.services import support
from tests.test_offers_cart import db  # noqa: F401
from tests.test_panel import env, login  # noqa: F401
from tests.test_panel_w3 import post


class FakeMessage:
    def __init__(self, text=None, photo=None, caption=None):
        self.text, self.caption, self.photo, self.contact = text, caption, photo, None
        for kind in ("document", "video", "voice", "audio", "video_note", "sticker"):
            setattr(self, kind, None)
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)


async def client(db, tg=300):  # noqa: F811
    user = User(telegram_id=tg, first_name="Азиз", username="aziz", language="ru", phone="+998901112233",
                region=await db.get(Region, 1))
    db.add(user)
    await db.commit()
    return user


async def test_client_messages_land_in_chat_and_staff_is_notified_once(env):  # noqa: F811
    user = await client(env.db)
    settings = SimpleNamespace(admin_ids={1}, web_url="https://partsbot.jacmotors.uz")
    first = FakeMessage("Есть передний бампер на T9?")
    assert support_handlers.registered(first, user)
    await support_handlers.client_writes(first, user, env.db, env.bot, settings)
    photo = FakeMessage(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="BIG")], caption="вот такой")
    await support_handlers.client_writes(photo, user, env.db, env.bot, settings)

    assert first.answers and "передано менеджеру" in first.answers[0] and photo.answers == []  # подтверждение — один раз
    to_admin = [t for chat_id, t in env.bot.sent if chat_id == 1]
    assert len(to_admin) == 1 and "передний бампер" in to_admin[0] and "/chat/" in to_admin[0]
    chat = await env.db.scalar(select(SupportChat).where(SupportChat.user_id == user.id))
    assert chat.unread == 2 and chat.last_text == "📷 Фото вот такой"
    msgs = await support.messages(env.db, chat.id)
    assert [(m.direction, m.file_kind, m.file_id) for m in msgs] == [("in", None, None), ("in", "photo", "BIG")]

    unregistered = User(telegram_id=301, language="ru")  # регистрация не закончена — шаги регистрации, не чат
    assert not support_handlers.registered(FakeMessage("привет"), unregistered)
    assert not support_handlers.registered(FakeMessage("/unknown"), user)


async def test_panel_chat_reply_note_poll_and_status(env):  # noqa: F811
    user = await client(env.db)
    got = await support.add_incoming(env.db, user, "Здравствуйте, нужен фильтр")
    chat_id = got.chat.id
    await login(env.client, *env.creds["admin"])

    assert (await env.client.get("/chat/counts")).json()["unread"] == 1
    page = (await env.client.get("/chat")).text
    assert "Азиз" in page and "нужен фильтр" in page and "💬 Чат" in page
    page = (await env.client.get(f"/chat/{chat_id}")).text  # открыли — прочитано
    assert "Здравствуйте, нужен фильтр" in page and "Последние заказы" in page
    assert (await env.client.get("/chat/counts")).json()["unread"] == 0

    token = __import__("re").search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = await env.client.post(f"/chat/{chat_id}/send", data={"csrf": token, "text": "Есть в наличии, 85 000 сум"},
                              headers={"X-Requested-With": "fetch"})
    body = r.json()
    assert body["ok"] and body["delivered"] and "85 000" in body["html"]
    assert (300, "💬 Менеджер JAC Motors:\n\nЕсть в наличии, 85 000 сум") in env.bot.sent
    sent_before = len(env.bot.sent)
    r = await env.client.post(f"/chat/{chat_id}/send", data={"csrf": token, "text": "Клиент VIP", "note": "1"},
                              headers={"X-Requested-With": "fetch"})
    assert r.json()["ok"] and len(env.bot.sent) == sent_before  # заметка клиенту не уходит
    assert "заметка" in r.json()["html"]

    poll = (await env.client.get(f"/chat/{chat_id}/poll?after=0")).json()
    assert poll["html"].count('class="bubble') == 3 and poll["assignee"]  # ответивший стал ответственным
    last = poll["last"]
    await support.add_incoming(env.db, user, "Спасибо, беру")
    poll = (await env.client.get(f"/chat/{chat_id}/poll?after={last}&seen=1")).json()
    assert "Спасибо, беру" in poll["html"] and poll["html"].count('class="bubble') == 1 and poll["unread"] == 0

    await env.client.post(f"/chat/{chat_id}/status", data={"csrf": token, "action": "close"})
    chat = await env.db.get(SupportChat, chat_id)
    await env.db.refresh(chat)
    assert chat.status == "closed"
    assert "Азиз" not in (await env.client.get("/chat/sidebar?tab=open")).text
    assert "Азиз" in (await env.client.get("/chat/sidebar?tab=closed")).text
    await support.add_incoming(env.db, user, "Ещё вопрос")  # клиент написал — диалог открылся сам
    await env.db.refresh(chat)
    assert chat.status == "open" and chat.unread == 1

    empty = await env.client.post(f"/chat/{chat_id}/send", data={"csrf": token, "text": "  "},
                                  headers={"X-Requested-With": "fetch"})
    assert empty.json()["ok"] is False


async def test_roles_client_card_and_files(env, tmp_path, monkeypatch):  # noqa: F811
    from app.services import chat_files
    monkeypatch.setattr(chat_files, "CACHE_DIR", tmp_path / "cache")
    user = await client(env.db)
    await login(env.client, *env.creds["admin"])
    r = await env.client.get(f"/chat/open/{user.id}")  # из карточки клиента — диалог создаётся
    assert r.status_code == 303 and r.headers["location"].startswith("/chat/")
    chat_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert "Открыть чат с клиентом" in (await env.client.get(f"/clients/{user.id}")).text
    r = await post(env.client, f"/clients/{user.id}/message", {"text": "Ваш заказ готов"}, f"/clients/{user.id}")
    assert r.headers["location"].startswith(f"/chat/{chat_id}")  # письмо из карточки — в историю чата
    assert any(m.text == "Ваш заказ готов" for m in await support.messages(env.db, chat_id))

    got = await support.add_incoming(env.db, user, "", file_id="DOC1", kind="document", file_name="схема.pdf")

    async def get_file(file_id):
        return SimpleNamespace(file_path="documents/x.pdf")

    async def download_file(path):
        return io.BytesIO(b"%PDF-1.4")
    env.bot.get_file, env.bot.download_file = get_file, download_file
    r = await env.client.get(f"/chat/file/{got.message.id}")
    assert r.status_code == 200 and r.content == b"%PDF-1.4" and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")  # PDF открывается прямо в чате
    r = await env.client.get(f"/chat/file/{got.message.id}?download=1")
    assert r.headers["content-disposition"].startswith("attachment")  # кнопка «⬇ Скачать»

    await login(env.client, *env.creds["operator"])  # оператор: видит и отвечает
    page = (await env.client.get(f"/chat/{chat_id}")).text
    assert "схема.pdf" in page and 'id="composer"' in page


async def test_reply_with_photo_upload(env):  # noqa: F811
    user = await client(env.db)
    sent = []

    async def send_photo(chat_id, photo, caption=None):
        sent.append((chat_id, photo.filename, caption))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="P_SMALL"), SimpleNamespace(file_id="P_BIG")])
    env.bot.send_photo = send_photo
    await login(env.client, *env.creds["admin"])
    chat_id = int((await env.client.get(f"/chat/open/{user.id}")).headers["location"].rsplit("/", 1)[1])
    page = (await env.client.get(f"/chat/{chat_id}")).text
    token = __import__("re").search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = await env.client.post(f"/chat/{chat_id}/send", data={"csrf": token, "text": "Вот эта деталь"},
                              files={"file": ("bumper.jpg", b"\xff\xd8\xff", "image/jpeg")},
                              headers={"X-Requested-With": "fetch"})
    assert r.json()["ok"] and sent == [(300, "bumper.jpg", "💬 Менеджер JAC Motors:\n\nВот эта деталь")]
    msg = await env.db.scalar(select(SupportMessage).where(SupportMessage.chat_id == chat_id))
    assert (msg.file_kind, msg.file_id) == ("photo", "P_BIG")


def test_chat_permissions():
    from app.services.roles import can
    assert can("operator", "chat.reply") and can("manager", "chat.reply") and can("admin", "chat.reply")
    assert can("viewer", "chat.view") and not can("viewer", "chat.reply")


async def test_live_updates_endpoint(env):  # noqa: F811
    """Одним запросом: новые сообщения открытого диалога, список (только если изменился), счётчики; без кэша."""
    user = await client(env.db)
    got = await support.add_incoming(env.db, user, "Первое")
    await login(env.client, *env.creds["admin"])
    r = await env.client.get(f"/chat/updates?chat={got.chat.id}&after=0&seen=1")
    d = r.json()
    assert r.headers["cache-control"] == "no-store"
    assert "Первое" in d["html"] and d["incoming"] == 1 and "Азиз" in d["list"] and d["unread"] == 0  # открыт — прочитан
    v, last = d["v"], d["last"]
    d = (await env.client.get(f"/chat/updates?chat={got.chat.id}&after={last}&seen=1&v={v}")).json()
    assert d["last"] is None and "list" not in d  # ничего нового — список не пересылаем
    await support.add_incoming(env.db, user, "Второе")
    d = (await env.client.get(f"/chat/updates?chat={got.chat.id}&after={last}&seen=0&v={v}")).json()
    assert "Второе" in d["html"] and "list" in d and d["unread"] == 1 and d["counts"]["unread"] == 1
    d = (await env.client.get("/chat/updates")).json()  # страница без открытого диалога — только список и счётчики
    assert "html" not in d and "Азиз" in d["list"]


async def test_media_shown_inside_chat(env, tmp_path, monkeypatch):  # noqa: F811
    """Фото, видео, голос — прямо в переписке; таблицы, Word, текст — предпросмотр; HTML — только скачать."""
    import zipfile

    import openpyxl

    from app.services import chat_files
    monkeypatch.setattr(chat_files, "CACHE_DIR", tmp_path / "cache")
    xlsx, docx = tmp_path / "price.xlsx", tmp_path / "letter.docx"
    book = openpyxl.Workbook()
    book.active.append(["Артикул", "Цена"])
    book.active.append(["2803101V6571", 1074400])
    book.save(xlsx)
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>Счёт на оплату</w:t></w:r></w:p><w:p><w:r><w:t>Итого: 85 000</w:t></w:r></w:p>'
                   '</w:body></w:document>')
    files = {"V": b"\x00\x00\x00\x18ftypmp4", "X": xlsx.read_bytes(), "W": docx.read_bytes(),
             "C": "Код;Цена\nA1;100\n".encode(), "H": b"<script>alert(1)</script>"}

    async def get_file(file_id):
        return SimpleNamespace(file_path=file_id)

    async def download_file(path):
        return io.BytesIO(files[path])
    env.bot.get_file, env.bot.download_file = get_file, download_file

    user = await client(env.db)
    video = (await support.add_incoming(env.db, user, "", "V", "video", "JAC M3 Van.mp4")).message
    table = (await support.add_incoming(env.db, user, "", "X", "document", "price.xlsx")).message
    word = (await support.add_incoming(env.db, user, "", "W", "document", "letter.docx")).message
    csv_ = (await support.add_incoming(env.db, user, "", "C", "document", "list.csv")).message
    html = (await support.add_incoming(env.db, user, "", "H", "document", "page.html")).message
    await support.add_incoming(env.db, user, "", "VO", "voice")
    await login(env.client, *env.creds["admin"])

    page = (await env.client.get(f"/chat/{video.chat_id}")).text
    assert f'<video class="media" controls preload="metadata" src="/chat/file/{video.id}"' in page
    assert "<audio controls" in page and 'data-view="table"' in page and 'data-view="word"' in page
    assert 'id="viewer"' in page and 'data-view="other"' not in page  # HTML — без «Открыть», только скачать

    r = await env.client.get(f"/chat/file/{video.id}", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.content == files["V"][:4] and r.headers["content-type"] == "video/mp4"  # перемотка
    pv = (await env.client.get(f"/chat/preview/{table.id}")).text
    assert "2803101V6571" in pv and "1074400" in pv and "<table>" in pv
    assert "Итого: 85 000" in (await env.client.get(f"/chat/preview/{word.id}")).text
    assert "A1" in (await env.client.get(f"/chat/preview/{csv_.id}")).text
    r = await env.client.get(f"/chat/file/{html.id}")
    assert r.headers["content-disposition"].startswith("attachment") and "html" not in r.headers["content-type"]
    assert chat_files.view_of(html).kind == "other"
