import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base
from app.database.repositories.users import UserRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        yield s
    await engine.dispose()


async def test_new_user_has_no_language(session):
    user = await UserRepository(session).get_or_create(telegram_id=1, first_name="Ivan")
    assert user.language is None


async def test_save_and_change_language(session):
    repo = UserRepository(session)
    user = await repo.get_or_create(telegram_id=2)
    user.phone = "+998900000000"
    await repo.set_language(user, "uz")
    again = await repo.get_by_telegram_id(2)
    assert again.language == "uz"

    await repo.set_language(again, "en")
    again = await repo.get_by_telegram_id(2)
    assert again.language == "en"
    assert again.phone == "+998900000000"  # остальные данные не сбрасываются


async def test_invalid_language_rejected(session):
    repo = UserRepository(session)
    user = await repo.get_or_create(telegram_id=3)
    with pytest.raises(ValueError):
        await repo.set_language(user, "de")


async def test_get_or_create_does_not_duplicate(session):
    repo = UserRepository(session)
    a = await repo.get_or_create(telegram_id=4)
    b = await repo.get_or_create(telegram_id=4, username="new")
    assert a.id == b.id and b.username == "new"
