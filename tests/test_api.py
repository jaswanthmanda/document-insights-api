import hashlib
import json

import asyncio
from uuid import uuid4

import httpx
from fastapi import status

from app import database
from app.database import connect_services, close_services
from app.main import app


def test_document_api_flow():
    async def run():
        await connect_services()
        user_id = f"test-{uuid4().hex}"

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost:8000",
            ) as client:
                # Health check
                response = await client.get("/health")
                assert response.status_code == 200

                # Submit a document
                response = await client.post(
                    "/documents",
                    json={
                        "user_id": user_id,
                        "title": "Test document",
                        "content": (
                            "FastAPI supports asynchronous APIs. "
                            "MongoDB stores document data."
                        ),
                    },
                )
                assert response.status_code == status.HTTP_201_CREATED
                data = response.json()
                document_id = data["document_id"]
                assert data["status"] == "queued"

                # Retrieve its status
                response = await client.get(
                    f"/documents/{document_id}"
                )
                assert response.status_code == 200
                assert response.json()["user_id"] == user_id

                # List documents with pagination
                response = await client.get(
                    f"/users/{user_id}/documents",
                    params={"page": 1, "page_size": 10},
                )
                assert response.status_code == 200
                assert response.json()["total"] == 1
                assert len(response.json()["items"]) == 1

                # Invalid ID must return 404
                response = await client.get("/documents/not-an-object-id")
                assert response.status_code == 404

                # Invalid input must fail Pydantic validation
                response = await client.post(
                    "/documents",
                    json={
                        "user_id": user_id,
                        "title": "",
                        "content": "Some content",
                    },
                )
                assert response.status_code == 422

                # Cache hit returns a completed document immediately.
                cached_content = "Previously summarized content"
                content_hash = hashlib.sha256(
                    cached_content.encode("utf-8")
                ).hexdigest()
                cached_summary = {
                    "summary": "Cached summary",
                    "key_points": ["Cached point"],
                    "word_count": 3,
                }
                await database.redis_client.set(
                    f"summary:{content_hash}",
                    json.dumps(cached_summary),
                    ex=3600,
                )

                response = await client.post(
                    "/documents",
                    json={
                        "user_id": user_id,
                        "title": "Cached document",
                        "content": cached_content,
                    },
                )
                assert response.status_code == 201
                cached_id = response.json()["document_id"]
                assert response.json()["status"] == "completed"

                response = await client.get(
                    f"/documents/{cached_id}"
                )
                assert response.json()["summary"] == cached_summary

                # Three uncached submissions are allowed; the fourth
                # active submission must be rejected.
                for i in range(2):
                    response = await client.post(
                        "/documents",
                        json={
                            "user_id": user_id,
                            "title": f"Rate test {i}",
                            "content": f"Unique rate-test content {i}",
                        },
                    )
                    assert response.status_code == 201

                response = await client.post(
                    "/documents",
                    json={
                        "user_id": user_id,
                        "title": "Over limit",
                        "content": "Another unique document",
                    },
                )
                assert response.status_code == 429

        finally:
            # This test assumes the worker is not running.
            await database.db.documents.delete_many(
                {"user_id": user_id}
            )
            await database.redis_client.delete(
                f"active_jobs:{user_id}"
            )
            await close_services()

    asyncio.run(run())
