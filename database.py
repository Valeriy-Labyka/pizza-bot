import os
import json
import logging
import asyncio
import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
pool = None

async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ Подключение к PostgreSQL установлено.")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к базе данных: {e}")
        raise

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                items TEXT NOT NULL,
                total INTEGER NOT NULL,
                address TEXT,
                phone TEXT,
                payment_method TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price_small INTEGER,
                price_large INTEGER,
                image_url TEXT
            )
        """)

        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        if count > 0:
            logger.info("ℹ️ Товары уже загружены.")
            return

        try:
            with open("menu_data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"❌ Ошибка чтения menu_data.json: {e}")
            return

        for category, items in data.items():
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                await conn.execute(
                    """
                    INSERT INTO products (category, name, description, price_small, price_large, image_url)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    category,
                    name,
                    item.get("description", ""),
                    item.get("price_small"),
                    item.get("price_large"),
                    item.get("image_url", "").strip()
                )
        logger.info("✅ Товары загружены в базу.")


async def save_order(user_id: int, items: list, total: int, address: str, payment_method: str, phone: str = ""):
    try:
        items_json = json.dumps(items, ensure_ascii=False)
    except Exception as e:
        logger.error(f"❌ Ошибка сериализации заказа: {e}")
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO orders (user_id, items, total, address, phone, payment_method)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            user_id, items_json, total, address, phone, payment_method
        )
        return row["id"] if row else None


async def get_user_orders(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, items, total, address, phone, payment_method, status, created_at FROM orders WHERE user_id = $1 ORDER BY id DESC",
            user_id
        )
    return _parse_orders(rows, include_user_id=False)


async def get_all_orders(limit: int = 10):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, items, total, address, phone, payment_method, status, created_at FROM orders ORDER BY id DESC LIMIT $1",
            limit
        )
    return _parse_orders(rows, include_user_id=True)


def _parse_orders(rows, include_user_id=False):
    orders = []
    for row in rows:
        try:
            items = json.loads(row["items"])
        except:
            items = []
        order = {
            "id": row["id"],
            "items": items,
            "total": row["total"],
            "address": row["address"],
            "phone": row["phone"],
            "payment_method": row["payment_method"],
            "status": row["status"],
            "created_at": row["created_at"]
        }
        if include_user_id:
            order["user_id"] = row["user_id"]
        orders.append(order)
    return orders


async def update_order_status(order_id: int, new_status: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE orders SET status = $1 WHERE id = $2 RETURNING user_id",
            new_status, order_id
        )
        return row["user_id"] if row else None


async def delete_old_completed_orders():
    from datetime import datetime, timedelta
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM orders WHERE status = ANY($1) AND created_at < $2",
            ["done", "cancelled"], one_hour_ago
        )
        deleted_count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        logger.info(f"🧹 Удалено завершённых/отменённых заказов: {deleted_count}")