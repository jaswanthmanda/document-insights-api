
# Document Insights API

An asynchronous document processing service built with Python, FastAPI, MongoDB, Redis, and Docker Compose. It simulates document summarization without requiring an external AI service.

## Features

- Submit documents for asynchronous processing.
- Track document status: `queued`, `processing`, `completed`, or `failed`.
- List a user's documents with pagination and optional status filtering.
- Enforce a maximum of three active documents per user using atomic Redis operations.
- Cache completed summaries by SHA-256 content hash with a configurable TTL.
- Run processing in a separate worker process.
- Expose a health endpoint for MongoDB and Redis.
- Validate requests using Pydantic and create MongoDB indexes.

## Architecture

- **FastAPI:** Request validation and REST endpoints.
- **MongoDB:** Document persistence, processing state, and summaries.
- **Redis:** Job queue, active-job counters, and summary cache.
- **Worker:** Claims queued documents atomically, simulates processing, and records success or failure.
- **Docker Compose:** Runs the API, worker, MongoDB, and Redis.

## Run locally

### Requirements

- Docker Desktop
- Docker Compose
- Python 3.11+
- Git

### Start the complete application

```bash
docker compose up --build -d
```

Open the interactive API documentation:

[http://localhost:8000/docs](http://localhost:8000/docs)

### Check service health

```bash
curl http://localhost:8000/health
```

### Stop the application

```bash
docker compose down
```

MongoDB data is stored in a named Docker volume. To remove the volume and its persisted data as well, run:

```bash
docker compose down -v
```

> **Note:** This command permanently removes Compose-managed volumes, including stored MongoDB data.

## API endpoints

### Submit a document

`POST /documents`

Example request:

```json
{
  "user_id": "user-123",
  "title": "Example document",
  "content": "This is the content to summarize."
}
```

Returns HTTP `201 Created` with a document ID and its initial status, or `completed` for a cache hit.

### Get document status

`GET /documents/{document_id}`

Returns the document status, summary when completed, and error details when failed.

### List user documents

`GET /users/{user_id}/documents?page=1&page_size=10&status=completed`

Supports pagination and optional status filtering.

### Health

`GET /health`

Checks MongoDB and Redis connectivity.

## Processing and caching assumptions

- Processing duration is configurable and defaults to 10–30 seconds.
- The worker randomly fails approximately 10% of jobs.
- Cached summaries expire after the configured TTL.
- Cache keys use the SHA-256 hash of document content, so identical content can reuse a summary across users.
- Cached submissions create a new completed document record without consuming an active-job slot.
- Redis is required to enforce the active-job limit. If the rate limiter is unavailable, uncached submissions fail with HTTP `503 Service Unavailable`.
- Cache lookup or write failures are logged; cache failures do not prevent processing where possible.

## Testing

### Run tests locally on Windows (PowerShell)

1. Copy the example environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Update the MongoDB and Redis URLs in `.env` to use `localhost`.

3. Activate the virtual environment:

   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

4. Set `PYTHONPATH` to the project root:

   ```powershell
   $env:PYTHONPATH = (Get-Location).Path
   ```

5. Run the test suite:

   ```powershell
   pytest -v
   ```

**Prerequisites:** Ensure MongoDB and Redis are running before executing the tests.

## Trade-offs and future improvements

- Add durable queue delivery and recovery for jobs interrupted by worker crashes.
- Replace expiring active-job counters with recoverable leases or per-job active sets.
- Add bounded retries with exponential backoff and a dead-letter queue.
- Add distributed deduplication for concurrent submissions with the same content hash.
- Add structured JSON logging, metrics, authentication, and authorization.
- Expand integration tests for worker failures, cache expiry, and concurrent submissions.
- Add CI checks and deployment manifests for AWS EKS.

This implementation prioritizes a small, understandable service while keeping API, persistence, caching, and background processing concerns separate.
