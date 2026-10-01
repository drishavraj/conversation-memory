# Automatic text processing

The queue is PostgreSQL-backed. Redis/Celery is not required for this worker implementation.

## Render
After the API's latest deployment is Live (including migrations):
1. New > Background Worker; select the same repository and main branch.
2. Runtime Docker, same region as PostgreSQL, choose a plan after reviewing its separate price.
3. Docker Command: `python -m app.worker --loop`
4. Environment: DATABASE_URL (same postgresql+psycopg internal URL), GEMINI_API_KEY, GENERATION_MODEL (the working gemini-3.8-flash for this deployment).
5. Start with one instance. No public port, owner token, or Redis is required for the worker.
6. Deploy. Logs should show `Worker started; checking durable queue`.
7. Submit a unique text entry using the API. Poll its detail until ready or failed; do not run a manual worker in parallel for this test.

Each queued job can incur an API charge. Existing queued entries are also processed when the worker starts; failed/completed jobs are skipped. Duplicate ingestion does not enqueue another job. Retries remain explicit via the API.

## Local Docker
Configure Gemini credentials and model in .env, then run `docker compose --profile processing up --build -d`. The API start script runs migrations; the worker waits and retries if schema is not ready. It prints safe error codes without provider bodies or connection secrets.

## Operations
The default polling interval is five seconds; --poll-seconds accepts 1–60. The worker processes one entry at a time, oldest uploads first. SIGTERM/SIGINT stops new claims; the current request may finish. If the hosting platform kills it earlier, the claim can remain processing. After confirming old workers are stopped, use `python -m app.worker --recover` for claims older than 15 minutes. Recovery is manual to avoid hidden repeat API charges. This release does not implement automatic leases, heartbeats or retry backoff for failed jobs.

26 tests pass with SQLite and simulated providers. Docker/Render worker deployment still needs live validation; API ingestion and Gemini extraction were previously tested live.
