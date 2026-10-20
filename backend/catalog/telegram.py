import io

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from catalog.config import Settings
from catalog.storage import InvalidPhoto


def catalog_keyboard(url: str) -> dict:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть каталог", web_app=WebAppInfo(url=url)),
    ]]).model_dump(exclude_none=True)


def make_bot(settings: Settings) -> Bot:
    return Bot(settings.bot_token.get_secret_value(), session=AiohttpSession(timeout=15))


class TelegramGateway:
    def __init__(self, bot: Bot, max_bytes: int):
        self.bot = bot
        self.max_bytes = max_bytes

    async def download_photo(self, file_id: str) -> bytes:
        file = await self.bot.get_file(file_id)
        if file.file_size and file.file_size > self.max_bytes:
            raise InvalidPhoto("Нужна фотография размером до 10 МБ.")
        if not file.file_path:
            raise InvalidPhoto("Telegram не вернул фотографию. Попробуйте ещё раз.")
        target = LimitedBuffer(self.max_bytes)
        await self.bot.download_file(file.file_path, destination=target, timeout=15)
        return target.getvalue()

    async def send(self, chat_id: int, payload: dict) -> None:
        await self.bot.send_message(chat_id=chat_id, **payload)


class LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise InvalidPhoto("Нужна фотография размером до 10 МБ.")
        return super().write(data)
