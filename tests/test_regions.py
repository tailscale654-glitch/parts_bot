import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.database import create_session_factory
from app.database.models import Base, Region
from app.database.repositories.regions import RegionRepository
from app.database.repositories.users import UserRepository
from app.handlers.start import main_menu_text
from app.services.localization import localized_name


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as s:
        s.add_all([
            Region(id=1, code="tashkent_city", name_ru="Ташкент", name_en="Tashkent", name_uz="Toshkent shahri", sort_order=10),
            Region(id=2, code="samarkand", name_ru="Самаркандская область", name_en=None, name_uz="Samarqand viloyati", sort_order=5),
            Region(id=3, code="old", name_ru="Отключённый", sort_order=1, active=False),
        ])
        await s.commit()
        yield s
    await engine.dispose()


async def test_list_active_sorted_and_filtered(session):
    regions = await RegionRepository(session).list_active()
    assert [r.code for r in regions] == ["samarkand", "tashkent_city"]


async def test_inactive_or_missing_region_not_returned(session):
    repo = RegionRepository(session)
    assert await repo.get_active(3) is None
    assert await repo.get_active(999) is None


async def test_region_name_fallback_to_russian(session):
    region = await RegionRepository(session).get_active(2)
    assert localized_name(region, "uz") == "Samarqand viloyati"
    assert localized_name(region, "en") == "Самаркандская область"  # нет перевода → русский


async def test_save_and_change_region_keeps_language(session):
    users = UserRepository(session)
    regions = RegionRepository(session)
    user = await users.get_or_create(telegram_id=10)
    await users.set_language(user, "en")
    await users.set_region(user, await regions.get_active(1))
    assert "📍 Region: Tashkent" in main_menu_text(user)

    await users.set_region(user, await regions.get_active(2))
    again = await users.get_by_telegram_id(10)
    assert again.region_id == 2 and again.language == "en"


async def test_language_change_keeps_region(session):
    users = UserRepository(session)
    user = await users.get_or_create(telegram_id=11)
    await users.set_region(user, await RegionRepository(session).get_active(1))
    await users.set_language(user, "uz")
    assert user.region_id == 1
    assert "Toshkent shahri" in main_menu_text(user)


async def test_new_user_menu_without_region(session):
    user = await UserRepository(session).get_or_create(telegram_id=12)
    await UserRepository(session).set_language(user, "ru")
    assert "не выбран" in main_menu_text(user)
