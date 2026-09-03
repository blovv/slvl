from aiogram.fsm.state import State, StatesGroup

class TikTokAdminStates(StatesGroup):
    waiting_api_key = State()
    waiting_quantity = State()
    waiting_message = State()
    waiting_keyphrases = State()
