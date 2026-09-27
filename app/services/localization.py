"""Локализация: все тексты интерфейса лежат в app/locales/*.json."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LANGUAGE = "ru"


class Localization:
    def __init__(self, locales_dir: Path = LOCALES_DIR, default: str = DEFAULT_LANGUAGE):
        self.default = default
        self.texts: dict[str, dict[str, str]] = {}
        for file in sorted(locales_dir.glob("*.json")):
            with file.open(encoding="utf-8") as f:
                self.texts[file.stem] = json.load(f)
        if default not in self.texts:
            raise RuntimeError(f"Файл локализации {default}.json не найден в {locales_dir}")

    @property
    def languages(self) -> list[str]:
        return list(self.texts)

    def t(self, lang: str | None, key: str, **kwargs) -> str:
        """Вернуть текст по ключу. Нет перевода → русский. Нет и его → сам ключ."""
        text = self.texts.get(lang or self.default, {}).get(key)
        if text is None:
            text = self.texts[self.default].get(key)
        if text is None:
            logger.warning("Missing localization key: %s", key)
            return key
        return text.format(**kwargs) if kwargs else text


def localized_name(obj, lang: str | None, field: str = "name") -> str:
    """Название объекта из БД на нужном языке: name_en / name_uz, если пусто — name_ru."""
    value = getattr(obj, f"{field}_{lang}", None) if lang else None
    return value or getattr(obj, f"{field}_{DEFAULT_LANGUAGE}")


i18n = Localization()
