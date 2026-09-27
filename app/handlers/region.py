from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.regions import RegionRepository
from app.database.repositories.users import UserRepository
from app.handlers.start import profile_view, region_prompt
from app.keyboards.phone import phone_keyboard
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
    saved = i18n.t(user.language, "region_saved", region=localized_name(region, user.language))
    await callback.answer()
    if not user.phone:
        # Регистрация: после региона просим телефон (кнопка «Отправить номер»)
        await callback.message.edit_text(saved)
        await callback.message.answer(i18n.t(user.language, "ask_phone"), reply_markup=phone_keyboard(user.language))
        return
    text, kb = profile_view(user)  # регион меняют из профиля — туда и возвращаемся
    await callback.message.edit_text(f"{saved}\n\n{text}", reply_markup=kb)
