import json

from app.services.localization import LOCALES_DIR, Localization, i18n


def test_all_languages_loaded():
    assert set(i18n.languages) == {"ru", "en", "uz"}


def test_all_locales_have_same_keys():
    ru_keys = set(json.loads((LOCALES_DIR / "ru.json").read_text(encoding="utf-8")))
    for lang in ("en", "uz"):
        keys = set(json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8")))
        assert keys == ru_keys, f"{lang}.json отличается от ru.json"


def test_translation_per_language():
    assert i18n.t("ru", "btn_catalog") == "🚗 Каталог"
    assert i18n.t("en", "btn_catalog") == "🚗 Catalog"
    assert i18n.t("uz", "btn_catalog") == "🚗 Katalog"


def test_fallback_to_russian(tmp_path):
    (tmp_path / "ru.json").write_text('{"hello": "Привет"}', encoding="utf-8")
    (tmp_path / "en.json").write_text("{}", encoding="utf-8")
    loc = Localization(tmp_path)
    assert loc.t("en", "hello") == "Привет"
    assert loc.t("xx", "hello") == "Привет"
    assert loc.t("en", "missing") == "missing"


def test_format_args():
    assert i18n.t("en", "region_line", region="Tashkent") == "📍 Region: Tashkent"
