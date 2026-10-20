import io
from pathlib import Path

import psycopg
import pytest
from PIL import Image
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from catalog.config import get_settings
from catalog.db import make_pool
from catalog.storage import ObjectStore
from catalog.telegram import make_bot


@pytest.fixture(scope="session", autouse=True)
def initialize():
    settings = get_settings()
    dsn = settings.database_url.get_secret_value()
    parts = conninfo_to_dict(dsn)
    assert parts["dbname"].endswith("_test"), "Tests require an isolated *_test database"
    admin_dsn = make_conninfo(dsn, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (parts["dbname"],)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(parts["dbname"])))
    with psycopg.connect(dsn) as conn:
        conn.execute(Path(__file__).parents[1].joinpath("catalog/schema.sql").read_text())
    ObjectStore(settings.model_copy(update={"s3_bucket": "catalog-test"})).initialize()


@pytest.fixture
def settings():
    return get_settings().model_copy(update={"s3_bucket": "catalog-test"})


@pytest.fixture
async def pool(settings):
    value = make_pool(settings)
    await value.open(wait=True)
    async with value.connection() as conn:
        await conn.execute("TRUNCATE telegram_outbox, products, admin_dialogs, telegram_updates RESTART IDENTITY CASCADE")
    yield value
    await value.close()


@pytest.fixture
def storage(settings):
    return ObjectStore(settings)


@pytest.fixture
async def bot(settings):
    value = make_bot(settings)
    yield value
    await value.session.close()


class FakeGateway:
    def __init__(self):
        target = io.BytesIO()
        Image.new("RGB", (32, 24), color="red").save(target, "JPEG")
        self.image = target.getvalue()
        self.sent = []
        self.fail = False

    async def download_photo(self, file_id):
        return self.image

    async def send(self, chat_id, payload):
        if self.fail:
            raise ConnectionError("simulated unavailable Telegram")
        self.sent.append((chat_id, payload))


@pytest.fixture
def gateway():
    return FakeGateway()
