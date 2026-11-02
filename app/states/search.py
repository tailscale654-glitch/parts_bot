from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    query = State()  # нажали «🔎 Поиск» — следующий текст ищем в каталоге (последний запрос — в данных: search_q)
