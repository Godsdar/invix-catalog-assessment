import asyncio
import logging
import signal

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Update

from catalog.config import get_settings
from catalog.db import make_pool
from catalog.handlers import make_dispatcher
from catalog.storage import ObjectStore
from catalog.telegram import TelegramGateway, make_bot

log = logging.getLogger("catalog.worker")


async def process_one(pool, dispatcher, bot, settings, storage, gateway) -> bool:
    async with pool.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute("""
                SELECT u.* FROM telegram_updates u
                WHERE u.done_at IS NULL AND u.available_at <= now()
                  AND NOT EXISTS (SELECT 1 FROM telegram_updates older
                      WHERE older.chat_id = u.chat_id AND older.update_id < u.update_id
                        AND older.done_at IS NULL)
                ORDER BY u.update_id FOR UPDATE OF u SKIP LOCKED LIMIT 1
            """)).fetchone()
            if row is None:
                return False
            # Savepoint rolls back all effects while preserving a durable retry schedule.
            try:
                async with conn.transaction():
                    await dispatcher.feed_update(
                        bot, Update.model_validate(row["payload"]), conn=conn,
                        settings=settings, storage=storage, gateway=gateway,
                        update_id=row["update_id"],
                    )
                    await conn.execute(
                        "UPDATE telegram_updates SET done_at=now(), last_error=NULL WHERE update_id=%s",
                        (row["update_id"],),
                    )
            except Exception as exc:
                # Never log Update bodies, file URLs, tokens or driver exception text.
                log.warning("Update %s failed: %s", row["update_id"], type(exc).__name__)
                delay = min(300, 2 ** min(row["attempts"] + 1, 8))
                await conn.execute(
                    "UPDATE telegram_updates SET attempts=attempts+1, last_error=%s, "
                    "available_at=now() + %s * interval '1 second' WHERE update_id=%s",
                    (type(exc).__name__, delay, row["update_id"]),
                )
    return True


async def send_one(pool, gateway) -> bool:
    async with pool.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute("""
                SELECT o.* FROM telegram_outbox o
                WHERE sent_at IS NULL AND available_at <= now()
                  AND NOT EXISTS (SELECT 1 FROM telegram_outbox older
                      WHERE older.chat_id=o.chat_id AND older.id<o.id AND older.sent_at IS NULL)
                ORDER BY id FOR UPDATE OF o SKIP LOCKED LIMIT 1
            """)).fetchone()
            if row is None:
                return False
            try:
                await gateway.send(row["chat_id"], row["payload"])
            except TelegramForbiddenError:
                # The user blocked the bot. Retain the reason but stop retrying this reply.
                await conn.execute(
                    "UPDATE telegram_outbox SET sent_at=now(), last_error='TelegramForbiddenError' "
                    "WHERE id=%s", (row["id"],),
                )
            except Exception as exc:
                delay = exc.retry_after if isinstance(exc, TelegramRetryAfter) else min(
                    300, 2 ** min(row["attempts"] + 1, 8))
                log.warning("Reply %s failed: %s", row["id"], type(exc).__name__)
                await conn.execute(
                    "UPDATE telegram_outbox SET attempts=attempts+1, last_error=%s, "
                    "available_at=now() + %s * interval '1 second' WHERE id=%s",
                    (type(exc).__name__, delay, row["id"]),
                )
            else:
                await conn.execute("UPDATE telegram_outbox SET sent_at=now(), last_error=NULL "
                                   "WHERE id=%s", (row["id"],))
    return True


async def main():
    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    settings.require_bot()
    pool = make_pool(settings)
    await pool.open(wait=True)
    bot = make_bot(settings)
    gateway = TelegramGateway(bot, settings.max_photo_bytes)
    dispatcher = make_dispatcher()
    storage = ObjectStore(settings)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    try:
        while not stopped.is_set():
            try:
                processed = await process_one(pool, dispatcher, bot, settings, storage, gateway)
                sent = await send_one(pool, gateway)
                if processed or sent:
                    continue
            except Exception as exc:
                log.warning("Worker dependency failure: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(stopped.wait(), timeout=0.5)
            except TimeoutError:
                pass
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
