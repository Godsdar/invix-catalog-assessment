from contextlib import asynccontextmanager

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Path, Query, Response
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from catalog.config import get_settings
from catalog.db import make_pool
from catalog.storage import ObjectStore


def create_app(pool=None, storage=None):
    @asynccontextmanager
    async def lifespan(app):
        settings = get_settings()
        app.state.pool = pool or make_pool(settings)
        app.state.storage = storage or ObjectStore(settings)
        if pool is None:
            await app.state.pool.open(wait=True)
        yield
        if pool is None:
            await app.state.pool.close()

    app = FastAPI(title="Catalog API", version="1.0.0", lifespan=lifespan, root_path="/api")

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        try:
            async with app.state.pool.connection() as conn:
                await conn.execute("SELECT 1 FROM schema_versions WHERE version = 1")
            await app.state.storage.ready()
        except Exception:
            raise HTTPException(503, "Dependencies unavailable") from None
        return {"status": "ready"}

    @app.get("/products")
    async def products(after: int = Query(0, ge=0, le=9223372036854775807), limit: int = Query(50, ge=1, le=100)):
        async with app.state.pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id, title, created_at FROM products WHERE id > %s ORDER BY id LIMIT %s",
                (after, limit + 1),
            )).fetchall()
        items = [{**row, "image_url": f"/api/products/{row['id']}/image"} for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > limit else None}

    @app.get("/products/{product_id}/image")
    async def image(product_id: int = Path(ge=1, le=9223372036854775807)):
        async with app.state.pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT image_key FROM products WHERE id = %s", (product_id,),
            )).fetchone()
        if row is None:
            raise HTTPException(404, "Product not found")
        try:
            data = await app.state.storage.get(row["image_key"])
        except (BotoCoreError, ClientError, ValueError):
            raise HTTPException(503, "Image temporarily unavailable") from None
        return Response(data, media_type="image/jpeg", headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        })

    @app.exception_handler(PoolTimeout)
    @app.exception_handler(DatabaseError)
    async def database_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)

    return app


app = create_app()
