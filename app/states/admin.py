from aiogram.fsm.state import State, StatesGroup


class ImportStates(StatesGroup):
    waiting_file = State()  # ждём Excel-файл
    confirm = State()  # файл проверен, ждём «Применить» / «Отмена»
