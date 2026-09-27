from app.database.models import Region, User
from app.handlers.start import profile_view
from app.keyboards.main import main_reply_keyboard, menu_action


def test_menu_buttons_recognized_in_all_languages():
    assert menu_action("🛍 Каталог") == "btn_catalog"
    assert menu_action("🛒 Cart") == "btn_cart"
    assert menu_action("👤 Profil") == "btn_profile"
    assert menu_action("просто текст") is None
    assert menu_action(None) is None


def test_reply_keyboard_layout():
    kb = main_reply_keyboard("uz")
    assert [[b.text for b in row] for row in kb.keyboard] == [
        ["🛍 Katalog", "🛒 Savat"],
        ["📦 Buyurtmalarim", "👤 Profil"],
        ["📞 Menejer"],
    ]


def test_profile_view():
    user = User(telegram_id=1, first_name="Ivan", last_name=None, phone="+998901234567", language="en",
                region=Region(code="t", name_ru="Ташкент", name_en="Tashkent"))
    text, kb = profile_view(user)
    assert "Ivan" in text and "+998901234567" in text and "Region: Tashkent" in text and "Language: English" in text
    assert [row[0].callback_data for row in kb.inline_keyboard] == ["profile:phone", "menu:region", "menu:language"]
