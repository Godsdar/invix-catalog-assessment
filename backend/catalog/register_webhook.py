import asyncio

from aiogram.types import BotCommand

from catalog.config import get_settings
from catalog.telegram import make_bot


async def main():
    settings = get_settings()
    settings.require_bot()
    bot = make_bot(settings)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Открыть каталог"),
            BotCommand(command="create", description="Создать товар (для администратора)"),
            BotCommand(command="cancel", description="Отменить добавление"),
        ])
        await bot.set_webhook(
            url=settings.mini_app_url + "/telegram/webhook",
            secret_token=settings.webhook_secret.get_secret_value(),
            allowed_updates=["message"], max_connections=40, drop_pending_updates=False,
        )
        info = await bot.get_webhook_info()
        print(f"Webhook configured; pending updates: {info.pending_update_count}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
