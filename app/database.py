from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis

from app.config import settings

mongo_client = None
redis_client = None
db = None


async def connect_services():
    global mongo_client, redis_client, db

    mongo_client = AsyncIOMotorClient(settings.mongodb_url)
    db = mongo_client[settings.mongodb_database]

    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
    )

    # Fail startup if either required service is unavailable.
    await mongo_client.admin.command("ping")
    await redis_client.ping()

    await db.documents.create_index(
        [("user_id", 1), ("created_at", -1)]
    )
    await db.documents.create_index(
        [("user_id", 1), ("status", 1)]
    )
    await db.documents.create_index(
        [("content_hash", 1)]
    )


async def close_services():
    if mongo_client:
        mongo_client.close()
    if redis_client:
        await redis_client.aclose()