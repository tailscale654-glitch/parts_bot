"""Автомобиль клиента вручную: модель → комплектация (если у модели их несколько) → цвет.

Обычно машину находит VIN (handlers/vin.py, данные из CarSale). Сюда попадают кнопкой «🚗 Выбрать модель
вручную» — если VIN не нашёлся или его нет под рукой. «🚗 Изменить автомобиль» открывает экран VIN.
Каталог клиента показывает только запчасти его модели (и раздел «Прочее»)."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
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


@router.callback_query(F.data.startswith("car:start"))  # и кнопки из старых сообщений профиля
async def start_car(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    from app.handlers.vin import ask_vin

    await callback.answer()
    await ask_vin(callback.message, user, state)


@router.callback_query(CarCB.filter(F.action == "manual"))
async def manual_car(callback: CallbackQuery, user: User) -> None:
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
    if len(cars.modifications(model)) > 1:
        await callback.message.edit_text(i18n.t(user.language, "choose_car_mod", model=model),
                                         reply_markup=mods_keyboard(model, user.language))
        return
    await _ask_color(callback, user)


@router.callback_query(CarCB.filter(F.action == "mod"))
async def set_mod(callback: CallbackQuery, callback_data: CarCB, user: User, session: AsyncSession) -> None:
    mods = cars.modifications(user.car_model)
    if not 0 <= callback_data.i < len(mods):
        await callback.answer()
        return
    await UserRepository(session).set_car(user, modification=mods[callback_data.i], color=None)
    await callback.answer()
    await _ask_color(callback, user)


async def _ask_color(callback: CallbackQuery, user: User) -> None:
    title = " · ".join(filter(None, [user.car_model, cars.mod_name(user.car_modification, user.language)]))
    await callback.message.edit_text(
        i18n.t(user.language, "choose_car_color", model=title),
        reply_markup=colors_keyboard(user.car_model, user.car_modification, user.language))


@router.callback_query(CarCB.filter(F.action == "color"))
async def set_color(callback: CallbackQuery, callback_data: CarCB, user: User, session: AsyncSession,
                    state: FSMContext | None = None) -> None:
    from app.handlers.vin import save_pending_vin

    colors = cars.colors(user.car_model, user.car_modification)
    if not user.car_model or not 0 <= callback_data.i < len(colors):
        await callback.answer()
        return
    await UserRepository(session).set_car(user, color=colors[callback_data.i])
    await save_pending_vin(user, session, state)  # VIN, который не нашёлся в CarSale, — тоже в профиль
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
