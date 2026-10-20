import asyncio

import httpx
import pytest
from psycopg.types.json import Jsonb

from catalog.api import create_app as api_app
from catalog.handlers import make_dispatcher
from catalog.storage import InvalidPhoto, normalize_photo
from catalog.telegram import LimitedBuffer
from catalog.webhook import create_app as webhook_app
from catalog.worker import process_one, send_one


def update(number, *, user=42, text=None, caption=None, photo=False, chat=None, **extra):
    message = {"message_id": number, "date": 1792454400,
               "chat": {"id": chat or user, "type": "private"},
               "from": {"id": user, "is_bot": False, "first_name": "Test"}, **extra}
    if text is not None:
        message["text"] = text
    if caption is not None:
        message["caption"] = caption
    if photo:
        message["photo"] = [{"file_id": "test-photo", "file_unique_id": "unique",
                             "width": 32, "height": 24, "file_size": 1000}]
    return {"update_id": number, "message": message}


async def enqueue(pool, payload):
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO telegram_updates(update_id,chat_id,payload) VALUES (%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (payload["update_id"], payload["message"]["chat"]["id"], Jsonb(payload)),
        )


async def rows(pool, table):
    assert table in {"telegram_updates", "admin_dialogs", "products", "telegram_outbox"}
    async with pool.connection() as conn:
        return await (await conn.execute(f"SELECT * FROM {table}")).fetchall()


async def run(pool, bot, settings, storage, gateway):
    return await process_one(pool, make_dispatcher(), bot, settings, storage, gateway)


async def test_webhook_auth_dedup_and_size(pool, settings):
    app = webhook_app(pool, settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            payload = update(1, text="/start")
            assert (await client.post("/telegram/webhook", json=payload)).status_code == 403
            headers = {"X-Telegram-Bot-Api-Secret-Token": settings.webhook_secret.get_secret_value()}
            responses = await asyncio.gather(*[
                client.post("/telegram/webhook", json=payload, headers=headers) for _ in range(5)
            ])
            assert all(result.status_code == 200 for result in responses)
            assert len(await rows(pool, "telegram_updates")) == 1
            assert (await client.post("/telegram/webhook", content=b"x" * (1024 * 1024 + 1),
                                      headers=headers)).status_code == 413
            assert (await client.post("/telegram/webhook", json={"update_id": "invalid"},
                                      headers=headers)).status_code == 422


async def test_start_and_regular_message_offer_catalog(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(1, text="/start"))
    await enqueue(pool, update(2, user=99, text="привет"))
    await run(pool, bot, settings, storage, gateway)
    await run(pool, bot, settings, storage, gateway)
    replies = sorted(await rows(pool, "telegram_outbox"), key=lambda r: r["id"])
    assert replies[0]["payload"]["text"] == "У меня есть товар"
    assert replies[0]["payload"]["reply_markup"]["keyboard"][0][0]["text"] == "Создать товар"
    assert replies[1]["payload"]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == settings.mini_app_url


async def test_create_product_and_browser_api(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(10, text="Создать товар"))
    await enqueue(pool, update(11, photo=True, caption="  Чайник  "))
    await run(pool, bot, settings, storage, gateway)
    # New dispatcher/process reads the previous replica's dialog from PostgreSQL.
    await run(pool, bot, settings, storage, gateway)
    products = await rows(pool, "products")
    assert len(products) == 1 and products[0]["title"] == "Чайник"
    assert not await rows(pool, "admin_dialogs")
    data = await storage.get(products[0]["image_key"])
    assert data.startswith(b"\xff\xd8")
    assert not await run(pool, bot, settings, storage, gateway)
    app = api_app(pool, storage)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/health/ready")).status_code == 200
            listing = (await client.get("/products")).json()
            assert listing["items"][0]["title"] == "Чайник"
            assert listing["next_cursor"] is None
            image = await client.get(f"/products/{products[0]['id']}/image")
            assert image.content == data and image.headers["content-type"] == "image/jpeg"
            assert (await client.get("/products/999/image")).status_code == 404
            assert (await client.get("/products?limit=101")).status_code == 422


async def test_non_admin_cannot_create(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(1, user=99, text="/create"))
    await enqueue(pool, update(2, user=99, photo=True, caption="Недопустимый товар"))
    await run(pool, bot, settings, storage, gateway)
    await run(pool, bot, settings, storage, gateway)
    assert not await rows(pool, "products")
    assert not await rows(pool, "admin_dialogs")
    assert "администратору" in (await rows(pool, "telegram_outbox"))[0]["payload"]["text"]


@pytest.mark.parametrize("kwargs", [
    {"text": "только название"}, {"photo": True},
    {"photo": True, "caption": "x" * 201},
    {"photo": True, "caption": "Альбом", "media_group_id": "group"},
])
async def test_invalid_input_preserves_dialog(pool, bot, settings, storage, gateway, kwargs):
    await enqueue(pool, update(1, text="/create"))
    await run(pool, bot, settings, storage, gateway)
    await enqueue(pool, update(2, **kwargs))
    await run(pool, bot, settings, storage, gateway)
    assert not await rows(pool, "products")
    assert len(await rows(pool, "admin_dialogs")) == 1


async def test_cancel_and_expired_dialog(pool, bot, settings, storage, gateway):
    for payload in [update(1, text="/create"), update(2, text="/cancel"),
                    update(3, photo=True, caption="Не создавать"), update(4, text="/create")]:
        await enqueue(pool, payload)
        await run(pool, bot, settings, storage, gateway)
    async with pool.connection() as conn:
        await conn.execute("UPDATE admin_dialogs SET expires_at=now()-interval '1 minute'")
    await enqueue(pool, update(5, photo=True, caption="Просрочено"))
    await run(pool, bot, settings, storage, gateway)
    assert not await rows(pool, "products")


async def test_s3_write_then_failure_and_retry(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(1, text="/create"))
    await run(pool, bot, settings, storage, gateway)
    await enqueue(pool, update(2, photo=True, caption="Повтор"))

    class CrashAfterPut:
        async def put(self, key, data):
            await storage.put(key, data)
            raise ConnectionError("simulated crash after S3 upload, before DB commit")

    await run(pool, bot, settings, CrashAfterPut(), gateway)
    assert not await rows(pool, "products")
    pending = next(row for row in await rows(pool, "telegram_updates") if row["update_id"] == 2)
    assert pending["attempts"] == 1 and pending["done_at"] is None
    assert (await storage.get("products/2.jpg")).startswith(b"\xff\xd8")
    async with pool.connection() as conn:
        await conn.execute("UPDATE telegram_updates SET available_at=now()")
    await run(pool, bot, settings, storage, gateway)
    assert len(await rows(pool, "products")) == 1
    assert len(await rows(pool, "telegram_outbox")) == 2


async def test_eight_workers_keep_chat_order_and_do_not_duplicate(pool, bot, settings, storage, gateway):
    for i in range(1, 9):
        await enqueue(pool, update(i * 2, user=42, chat=1000 + i, text="/create"))
        await enqueue(pool, update(i * 2 + 1, user=42, chat=1000 + i, photo=True, caption=f"Товар {i}"))
    async def drain():
        for _ in range(20):
            await run(pool, bot, settings, storage, gateway)
            await asyncio.sleep(0)
    await asyncio.gather(*[drain() for _ in range(8)])
    assert len(await rows(pool, "products")) == 8
    assert all(row["done_at"] is not None for row in await rows(pool, "telegram_updates"))
    assert len(await rows(pool, "telegram_outbox")) == 16


async def test_outbox_retries_then_sends_once(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(1, text="/start"))
    await run(pool, bot, settings, storage, gateway)
    gateway.fail = True
    await send_one(pool, gateway)
    assert not gateway.sent
    assert (await rows(pool, "telegram_outbox"))[0]["attempts"] == 1
    gateway.fail = False
    async with pool.connection() as conn:
        await conn.execute("UPDATE telegram_outbox SET available_at=now()")
    await asyncio.gather(*[send_one(pool, gateway) for _ in range(5)])
    assert len(gateway.sent) == 1


async def test_keyset_pagination(pool, bot, settings, storage, gateway):
    for i in range(1, 4):
        await enqueue(pool, update(2 * i, text="/create"))
        await enqueue(pool, update(2 * i + 1, photo=True, caption=f"Товар {i}"))
        await run(pool, bot, settings, storage, gateway)
        await run(pool, bot, settings, storage, gateway)
    app = api_app(pool, storage)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            first = (await client.get("/products?limit=2")).json()
            second = (await client.get(f"/products?after={first['next_cursor']}&limit=2")).json()
            assert [p["title"] for p in first["items"] + second["items"]] == ["Товар 1", "Товар 2", "Товар 3"]
            assert second["next_cursor"] is None


async def test_corrupt_image_rejected_without_losing_dialog(pool, bot, settings, storage, gateway):
    await enqueue(pool, update(1, text="/create"))
    await enqueue(pool, update(2, photo=True, caption="Невалидное фото"))
    gateway.image = b"<script>alert(1)</script>"
    await run(pool, bot, settings, storage, gateway)
    await run(pool, bot, settings, storage, gateway)
    assert not await rows(pool, "products")
    assert len(await rows(pool, "admin_dialogs")) == 1


def test_image_limits_and_normalization(gateway):
    assert normalize_photo(gateway.image, 10000).startswith(b"\xff\xd8")
    with pytest.raises(InvalidPhoto):
        normalize_photo(gateway.image, 1)
    with pytest.raises(InvalidPhoto):
        normalize_photo(b"not image", 10000)
    target = LimitedBuffer(3)
    with pytest.raises(InvalidPhoto):
        target.write(b"1234")
