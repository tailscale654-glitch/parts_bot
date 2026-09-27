import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base
from app.database.repositories.users import UserRepository
from app.utils.validators import normalize_phone


@pytest.mark.parametrize("raw,expected", [
    ("+998901234567", "+998901234567"),
    ("998901234567", "+998901234567"),   # Telegram иногда присылает без «+»
    ("+998 (90) 123-45-67", "+998901234567"),
    ("123", None),
    ("", None),
    (None, None),
    ("1" * 16, None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


async def test_phone_saved_and_other_fields_kept():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(telegram_id=5)
        await repo.set_language(user, "uz")
        await repo.set_phone(user, "+998901234567")
        again = await repo.get_by_telegram_id(5)
        assert again.phone == "+998901234567" and again.language == "uz"
    await engine.dispose()
