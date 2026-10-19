import asyncio
import logging
import random
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument
from redis.exceptions import RedisError

from app.config import settings
from app.database import connect_services, close_services
from app import database
from app.main import QUEUE_KEY, RELEASE_JOB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def make_summary(content: str) -> dict:
    """Simulated summarization; no external AI service required."""
    words = content.split()
    sentences = [
        part.strip()
        for part in content.replace("!", ".").replace("?", ".").split(".")
        if part.strip()
    ]

    return {
        "summary": " ".join(words[:40]),
        "key_points": sentences[:3],
        "word_count": len(words),
    }


async def process_jobs():
    while True:
        # Block briefly instead of continuously polling Redis.
        item = await database.redis_client.brpop(QUEUE_KEY, timeout=5)
        if not item:
            continue

        _, document_id = item
        if not ObjectId.is_valid(document_id):
            logger.error("Invalid document ID in queue: %s", document_id)
            continue

        now = datetime.now(timezone.utc)

        # Atomic claim: only one worker can transition queued -> processing.
        doc = await database.db.documents.find_one_and_update(
            {"_id": ObjectId(document_id), "status": "queued"},
            {"$set": {"status": "processing", "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )

        if doc is None:
            logger.warning("Job already claimed or missing: %s", document_id)
            continue

        active_key = f"active_jobs:{doc['user_id']}"

        try:
            delay = random.randint(
                settings.processing_min_seconds,
                settings.processing_max_seconds,
            )
            await asyncio.sleep(delay)

            if random.random() < settings.worker_failure_rate:
                raise RuntimeError("Simulated processing failure")

            summary = make_summary(doc["content"])
            completed_at = datetime.now(timezone.utc)

            await database.db.documents.update_one(
                {"_id": doc["_id"], "status": "processing"},
                {"$set": {
                    "status": "completed",
                    "summary": summary,
                    "updated_at": completed_at,
                    "error": None,
                }},
            )

            try:
                await database.redis_client.set(
                    f"summary:{doc['content_hash']}",
                    __import__("json").dumps(summary),
                    ex=settings.cache_ttl_seconds,
                )
            except RedisError:
                # Processing succeeded; caching is optional.
                logger.exception("Could not cache summary for %s", document_id)

            logger.info("Document completed: %s", document_id)

        except Exception as exc:
            logger.exception("Document processing failed: %s", document_id)
            await database.db.documents.update_one(
                {"_id": doc["_id"], "status": "processing"},
                {"$set": {
                    "status": "failed",
                    "error": str(exc),
                    "updated_at": datetime.now(timezone.utc),
                }},
            )

        finally:
            try:
                # await database.redis_client.eval(RELEASE_JOB, 1, active_key)
                await database.redis_client.eval(RELEASE_JOB, 1, active_key)
            except RedisError:
                logger.exception(
                    "Could not release active-job count for %s",
                    document_id,
                )


async def main():
    await connect_services()
    logger.info("Background worker started")
    try:
        await process_jobs()
    finally:
        await close_services()


if __name__ == "__main__":
    asyncio.run(main())