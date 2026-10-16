"""Автомобиль клиента: модель → цвет → модификация (если у модели их несколько).

При регистрации — после региона, перед телефоном. Из профиля — «🚗 Изменить автомобиль».
Каталог клиента показывает только запчасти его модели (и раздел «Прочее»)."""
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories.users import UserRepository
from app.handlers.catalog import models_view
from app.keyboards.car import CarCB, colors_keyboard, mods_keyboard
from app.keyboards.car import models_keyboard as car_models_keyboard
from app.keyboards.phone import phone_keyboard
from app.services import cars
from app.services.localization import i18n

router = Router(name="car")


@router.callback_query(CarCB.filter(F.action == "start"))
async def start_car(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await callback.message.answer(i18n.t(user.language, "choose_car_model"), reply_markup=car_models_keyboard())


@router.callback_query(CarCB.filter(F.action == "model"))
async def set_model(callback: CallbackQuery, callback_data: CarCB, user: User, session: AsyncSession) -> None:
    models = cars.models()
    if not 0 <= callback_data.i < len(models):  # не доверяем данным из Telegram
        await callback.answer()
        return
    model = models[callback_data.i]
    await UserRepository(session).set_car(user, model=model, modification=None, color=None)
    await callback.answer()
    await callback.message.edit_text(i18n.t(user.language, "choose_car_color", model=model),
                                     reply_markup=colors_keyboard(user.language))


@router.callback_query(CarCB.filter(F.action == "color"))
async def set_color(callback: CallbackQuery, callback_data: CarCB, user: User, session: AsyncSession) -> None:
    if callback_data.key not in cars.COLORS or not user.car_model:
        await callback.answer()
        return
    await UserRepository(session).set_car(user, color=callback_data.key)
    await callback.answer()
    if len(cars.modifications(user.car_model)) > 1:
        await callback.message.edit_text(i18n.t(user.language, "choose_car_mod", model=user.car_model),
                                         reply_markup=mods_keyboard(user.car_model, user.language))
        return
    await _finish(callback, user, session)


@router.callback_query(CarCB.filter(F.action == "mod"))
async def set_mod(callback: CallbackQuery, callback_data: CarCB, user: User, session: AsyncSession) -> None:
    mods = cars.modifications(user.car_model)
    if callback_data.i != -1 and not 0 <= callback_data.i < len(mods):
        await callback.answer()
        return
    await UserRepository(session).set_car(user, modification=mods[callback_data.i] if callback_data.i >= 0 else None)
    await callback.answer()
    await _finish(callback, user, session)


async def _finish(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    lang = user.language
    await callback.message.edit_text(i18n.t(lang, "car_saved", car=cars.car_text(user, lang)))
    if not user.phone:  # регистрация: дальше — телефон
        await callback.message.answer(i18n.t(lang, "ask_phone"), reply_markup=phone_keyboard(lang))
        return
    text, kb = await models_view(user, session)  # сразу каталог для нового автомобиля
    await callback.message.answer(text, reply_markup=kb)
