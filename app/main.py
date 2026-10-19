import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query, Request, status
from redis.exceptions import RedisError

from app.database import connect_services, close_services
from app.database import connect_services, close_services
from app import database
# from app.database import db, redis_client
from app.config import settings
from app.schemas import (
    DocumentAccepted,
    DocumentCreate,
    DocumentListResponse,
    DocumentResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_KEY = "document_jobs"

# Increment only when the user's active count is below 3.
RESERVE_JOB = """
local n = tonumber(redis.call('GET', KEYS[1]) or '0')
if n >= tonumber(ARGV[1]) then
    return 0
end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return 1
"""

RELEASE_JOB = """
local n = tonumber(redis.call('GET', KEYS[1]) or '0')
if n > 0 then
    return redis.call('DECR', KEYS[1])
end
return 0
"""


def serialize(doc: dict) -> dict:
    return {
        "document_id": str(doc["_id"]),
        "user_id": doc["user_id"],
        "title": doc["title"],
        "status": doc["status"],
        "summary": doc.get("summary"),
        "error": doc.get("error"),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_services()
    logger.info("Document Insights API started")
    try:
        yield
    finally:
        await close_services()


app = FastAPI(
    title="Document Insights API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    try:
        await database.db.command("ping")
        await redis_client.ping()
        return {"status": "ok", "mongodatabase.db": "ok", "redis": "ok"}
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(
            status_code=503,
            detail="A required dependency is unavailable",
        ) from exc


@app.post(
    "/documents",
    response_model=DocumentAccepted,
    status_code=status.HTTP_201_CREATED,
)
async def submit_document(payload: DocumentCreate):
    content_hash = hashlib.sha256(
        payload.content.encode("utf-8")
    ).hexdigest()
    cache_key = f"summary:{content_hash}"
    now = datetime.now(timezone.utc)

    # Cache is an optimization: if reading it fails, proceed uncached.
    cached_summary = None
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            cached_summary = json.loads(cached)
    except (RedisError, ValueError):
        logger.warning("Cache lookup failed; proceeding without cache")

    # Cached documents are already complete and consume no active slot.
    if cached_summary is not None:
        doc = {
            "user_id": payload.user_id,
            "title": payload.title,
            "content": payload.content,
            "content_hash": content_hash,
            "status": "completed",
            "summary": cached_summary,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await database.db.documents.insert_one(doc)
        return DocumentAccepted(
            document_id=str(result.inserted_id),
            status="completed",
        )

    active_key = f"active_jobs:{payload.user_id}"

    # Redis is mandatory for enforcing the concurrency limit.
    try:
        reserved = await redis_client.eval(
            RESERVE_JOB, 1, active_key, 3, 86400
        )
    except RedisError as exc:
        logger.exception("Rate limiter unavailable")
        raise HTTPException(
            status_code=503,
            detail="Rate limiting service unavailable; retry later",
        ) from exc

    if not reserved:
        raise HTTPException(
            status_code=429,
            detail="Maximum of 3 active documents reached",
        )

    doc = {
        "user_id": payload.user_id,
        "title": payload.title,
        "content": payload.content,
        "content_hash": content_hash,
        "status": "queued",
        "summary": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    inserted_id = None
    try:
        result = await database.db.documents.insert_one(doc)
        inserted_id = result.inserted_id

        await redis_client.rpush(QUEUE_KEY, str(inserted_id))
    except Exception as exc:
        logger.exception("Document submission failed")
        if inserted_id is not None:
            await database.db.documents.delete_one({"_id": inserted_id})
        await redis_client.eval(RELEASE_JOB, 1, active_key)
        raise HTTPException(
            status_code=503,
            detail="Could not queue document; retry later",
        ) from exc

    logger.info("Document queued: %s", inserted_id)
    return DocumentAccepted(
        document_id=str(inserted_id),
        status="queued",
    )


@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str):
    if not ObjectId.is_valid(document_id):
        raise HTTPException(status_code=404, detail="Document not found")

    doc = await database.db.documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return serialize(doc)


@app.get(
    "/users/{user_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    document_status: str | None = Query(
        None, alias="status",
        pattern="^(queued|processing|completed|failed)$",
    ),
):
    query = {"user_id": user_id}
    if document_status:
        query["status"] = document_status

    total = await database.db.documents.count_documents(query)
    cursor = (
        database.db.documents.find(query)
        .sort("created_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize(doc) async for doc in cursor]

    return DocumentListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )