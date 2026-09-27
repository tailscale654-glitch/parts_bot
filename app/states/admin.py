from aiogram.fsm.state import State, StatesGroup


class ImportStates(StatesGroup):
    waiting_file = State()  # ждём Excel-файл
    confirm = State()  # файл проверен, ждём «Применить» / «Отмена»


class AdminStates(StatesGroup):
    search_order = State()  # ждём номер заказа


class ChatStates(StatesGroup):
    writing = State()  # пишем сообщение по заказу (order_id и to — в данных состояния)
