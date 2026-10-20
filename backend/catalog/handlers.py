import asyncio

from aiogram import Dispatcher, Router
from aiogram.types import Message
from psycopg.types.json import Jsonb

from catalog.storage import InvalidPhoto, normalize_photo
from catalog.telegram import catalog_keyboard


def make_dispatcher():
    router = Router()

    @router.message()
    async def handle(message: Message, conn, settings, storage, gateway, update_id: int):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id if message.from_user else None
        is_admin = user_id in settings.admins
        text = (message.text or "").strip()
        command = text.split()[0].split("@")[0] if text else ""
        reply = "У меня есть товар"
        markup = catalog_keyboard(settings.mini_app_url)

        if command == "/create" or text == "Создать товар":
            if not is_admin:
                reply = "Добавление товаров доступно только администратору."
            else:
                await conn.execute(
                    "INSERT INTO admin_dialogs(chat_id, user_id, expires_at) "
                    "VALUES (%s, %s, now() + interval '30 minutes') "
                    "ON CONFLICT (chat_id) DO UPDATE SET user_id = EXCLUDED.user_id, "
                    "expires_at = EXCLUDED.expires_at",
                    (message.chat.id, user_id),
                )
                reply = "Отправьте название товара и фотографию одним сообщением: фото с подписью."
        elif command == "/cancel":
            await conn.execute("DELETE FROM admin_dialogs WHERE chat_id = %s", (message.chat.id,))
            reply = "Добавление отменено. У меня есть товар"
        elif command == "/start":
            if is_admin:
                # Reply keyboard can contain both WebApp and the create action in a private chat.
                markup = {"keyboard": [[{"text": "Создать товар"}],
                          [{"text": "Открыть каталог", "web_app": {"url": settings.mini_app_url}}]],
                          "resize_keyboard": True}
        elif is_admin:
            pending = await (await conn.execute(
                "SELECT 1 FROM admin_dialogs WHERE chat_id = %s AND user_id = %s "
                "AND expires_at > now()", (message.chat.id, user_id),
            )).fetchone()
            if pending:
                title = (message.caption or "").strip()
                if not message.photo or not title:
                    reply = "Нужны фото и название в подписи к нему, одним сообщением."
                elif len(title) > 200:
                    reply = "Название должно содержать от 1 до 200 символов."
                elif message.media_group_id:
                    reply = "Отправьте одну фотографию с подписью, без альбома."
                else:
                    photo = message.photo[-1]
                    try:
                        if photo.file_size and photo.file_size > settings.max_photo_bytes:
                            raise InvalidPhoto("Нужна фотография размером до 10 МБ.")
                        raw = await gateway.download_photo(photo.file_id)
                        data = await asyncio.to_thread(normalize_photo, raw, settings.max_photo_bytes)
                    except InvalidPhoto as exc:
                        reply = str(exc)
                    else:
                        # A retried update overwrites the same object, including after DB rollback.
                        key = f"products/{update_id}.jpg"
                        await storage.put(key, data)
                        await conn.execute(
                            "INSERT INTO products(source_update_id, title, image_key) VALUES (%s,%s,%s) "
                            "ON CONFLICT (source_update_id) DO NOTHING", (update_id, title, key),
                        )
                        await conn.execute("DELETE FROM admin_dialogs WHERE chat_id = %s",
                                           (message.chat.id,))
                        reply = f"Товар «{title}» создан."
        await conn.execute(
            "INSERT INTO telegram_outbox(source_update_id, chat_id, payload) VALUES (%s,%s,%s) "
            "ON CONFLICT (source_update_id) DO NOTHING",
            (update_id, message.chat.id, Jsonb({"text": reply, "reply_markup": markup})),
        )

    dispatcher = Dispatcher(disable_fsm=True)
    dispatcher.include_router(router)
    return dispatcher
