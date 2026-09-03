from aiogram.types import BotCommand
from tgbot.telegrambot import TelegramBot

async def on_telegram_bot_init(tgbot: TelegramBot):
    try:
        current = await tgbot.bot.get_my_commands()
        if not any(c.command == "tiktok" for c in current):
            await tgbot.bot.set_my_commands(current + [BotCommand(command="tiktok", description="TikTok SMM — админ-панель")])
    except Exception:
        pass
