from pathlib import Path

import psycopg

from catalog.config import get_settings
from catalog.storage import ObjectStore


def main():
    settings = get_settings()
    with psycopg.connect(settings.database_url.get_secret_value()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(73945123)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text())
    ObjectStore(settings).initialize()
    print("Schema v1 and private S3 bucket are ready")


if __name__ == "__main__":
    main()
