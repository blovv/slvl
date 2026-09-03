from playerokapi.enums import EventTypes

from .meta import *

_module = None

def set_module(module):
    global _module
    _module = module

def get_module():
    return _module

from .handlers import on_module_enabled, on_playerok_init, on_new_deal, on_new_message
from .tgbot_init import on_telegram_bot_init
from .tgbot import router as telegram_router

BOT_EVENT_HANDLERS = {
    "ON_MODULE_ENABLED": [on_module_enabled],
    "ON_PLAYEROK_BOT_INIT": [on_playerok_init],
    "ON_TELEGRAM_BOT_INIT": [on_telegram_bot_init],
}

PLAYEROK_EVENT_HANDLERS = {
    EventTypes.NEW_DEAL: [on_new_deal],
    EventTypes.NEW_MESSAGE: [on_new_message],
}

TELEGRAM_BOT_ROUTERS = [telegram_router]
