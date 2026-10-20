from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from catalog.config import Settings


def make_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=1,
        max_size=settings.db_pool_size,
        open=False,
        timeout=5,
        kwargs={"row_factory": dict_row},
    )
