from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.regions import RegionRepository
from app.database.repositories.users import UserRepository
from app.handlers.start import main_menu_text, region_prompt
from app.keyboards.main import main_menu_keyboard
from app.services.localization import i18n, localized_name

router = Router(name="region")


@router.callback_query(F.data == "menu:region")
async def ask_region(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    text, kb = await region_prompt(user, session, with_back=user.region_id is not None)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("region:"))
async def set_region(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    raw_id = callback.data.split(":", 1)[1]
    region = await RegionRepository(session).get_active(int(raw_id)) if raw_id.isdigit() else None
    if region is None:  # не доверяем данным из Telegram: id мог быть подделан или регион отключён
        await callback.answer(i18n.t(user.language, "region_unavailable"), show_alert=True)
        return
    await UserRepository(session).set_region(user, region)
    await callback.answer(i18n.t(user.language, "region_saved", region=localized_name(region, user.language)))
    await callback.message.edit_text(main_menu_text(user), reply_markup=main_menu_keyboard(user.language))
