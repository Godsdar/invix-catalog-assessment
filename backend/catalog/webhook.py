import hmac
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from psycopg.types.json import Jsonb

from catalog.config import get_settings
from catalog.db import make_pool

MAX_BODY = 1024 * 1024


def create_app(pool=None, settings=None):
    settings = settings or get_settings()
    settings.require_bot()

    @asynccontextmanager
    async def lifespan(app):
        app.state.pool = pool or make_pool(settings)
        if pool is None:
            await app.state.pool.open(wait=True)
        yield
        if pool is None:
            await app.state.pool.close()

    app = FastAPI(title="Telegram webhook", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health/ready")
    async def ready():
        async with app.state.pool.connection() as conn:
            await conn.execute("SELECT 1 FROM telegram_updates LIMIT 1")
        return {"status": "ready"}

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided.encode(), settings.webhook_secret.get_secret_value().encode()):
            raise HTTPException(403, "Invalid webhook secret")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "Update too large")
        try:
            update = Update.model_validate_json(bytes(body))
        except (ValidationError, ValueError):
            raise HTTPException(422, "Invalid update") from None
        if update.message is None or update.message.chat.type != "private":
            return {"ok": True}
        async with app.state.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO telegram_updates(update_id, chat_id, payload) VALUES (%s,%s,%s) "
                "ON CONFLICT (update_id) DO NOTHING",
                (update.update_id, update.message.chat.id,
                 Jsonb(update.model_dump(mode="json", exclude_none=True))),
            )
        # Acknowledgement follows commit; failed commits cause Telegram to retry.
        return {"ok": True}

    return app


def app():
    return create_app()
