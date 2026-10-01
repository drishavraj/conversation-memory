# Conversation Memory

Open-source backend for a private conversation-memory application.

## Implemented
- Owner bearer-token authentication; token must be at least 32 characters.
- Alembic migrations with Personal, Side Projects, and Office themes.
- Text entries preserving original content and optional timezone-aware event date.
- Atomic creation of an entry and durable processing-job record.
- Theme-filtered lists, pagination, entry detail, and health endpoint.

## Not implemented yet
Audio/file upload, projects, corrections/supersession, search, browser sessions, and Lovable UI remain unimplemented. Text processing is available through a manual worker command. Live Gemini has not been tested.

## Docker setup
Copy `.env.example` to `.env`. Set a long random database password (URL-safe letters/digits) and independent owner token. Never commit `.env`.

```sh
docker compose up --build -d
docker compose exec api python -m alembic upgrade head
```

Visit http://localhost:8000/docs. Click Authorize and enter your owner token. Use POST /api/entries/text with:

```json
{"text":"Rahul said credentials are expected Friday.","title":"Sample call","theme_id":"office","event_at":"2026-10-01T12:00:00+05:30"}
```

Omit theme_id to mark classification as needs_review. No AI classification currently runs. API uses one owner per installation. Do not put the bearer token in frontend source; browser session authentication will be added before the UI. Health is unauthenticated but does not disclose connection errors. API binds to localhost; database and Redis ports are not exposed.

## Run automated tests without Docker
Use a virtual environment, then:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Six tests cover authorization, theme seed data, ingestion/job persistence, theme filtering, input validation, missing entries, and health. Tests run migrations against isolated SQLite databases; PostgreSQL/Redis and Docker builds are not verified in this workspace.

## Data safety
Original text and database records are private. Never commit recordings, transcripts, secrets, or backups. This is an early backend milestone, not a production deployment.

## Roadmap
Gemini provider and worker; evidence-backed knowledge extraction; cited retrieval and corrections; files/audio; Lovable PWA; deployment and backup documentation.

## Text processing milestone
Set GEMINI_API_KEY and GENERATION_MODEL server-side in .env, selecting an available Gemini model that supports generateContent structured JSON. Restart the API container after changing configuration. Never place the key in browser code or Git.

After migrations and ingestion, process one queued entry:

```sh
docker compose exec api python -m app.worker
```

Run once per queued entry. This milestone uses a manually invoked database-backed worker; continuous Celery scheduling is not wired up yet. Processing stores English text, summary, theme suggestion, and evidence-backed knowledge objects atomically. The selected entry theme is never overwritten. Individual objects may have different themes. Unknown themes remain null.

GET /api/entries/{id}/knowledge retrieves results; POST /api/entries/{id}/retry requeues failed jobs. No silent automatic retries or repeat charges. After stopping crashed workers, `python -m app.worker --recover` requeues claims older than 15 minutes. Do not recover while old workers are active.

Quote validation verifies exact source membership, not factual correctness of the interpretation. User review and corrections remain necessary and will be added next. Due dates are conservatively rejected without an event timestamp. Gemini integration uses generateContent REST structured JSON and a configurable model; compatibility and quality must be confirmed by a live test.

Verification: 15 tests pass against SQLite with simulated AI/HTTP responses. Covers quote offsets, atomic failures, retries, preservation of selected theme, tentative decisions, unknown date handling, and redacted errors. Docker/PostgreSQL/Redis/live Gemini remain untested.

## Corrections and retrieval milestone
- GET /api/actions: status active/completed/dismissed, optional theme_id and exact owner filter.
- PATCH /api/knowledge/{id}: include expected_version and reason; update text, theme_id, owner, due_date, certainty or status. Only actions may be completed. A stale expected_version returns 409.
- GET /api/knowledge/{id}/history: before/after snapshots and reason.
- GET /api/search?q=UAT&theme_id=office: literal case-insensitive keyword search in active knowledge text and original evidence, with source URLs and character offsets. This is not semantic retrieval or an AI-generated answer.

Semantic corrections mark the object user_corrected while retaining original evidence for provenance. The source quote supports the original extraction, not necessarily the user's correction. Search may match retained original evidence; inspect origin/history before interpreting it. Dismissed and completed items are excluded from search. Entry detail still returns those objects for audit and labels status. Theme scope applies to knowledge-item theme, not primary entry theme.

Migration 0003 adds versioning and audit history. Existing original sources remain unchanged. Automatic contradiction reconciliation and memory validity periods are not yet implemented. Tests cover history, stale-edit rejection, action completion, theme scope, dismissal, authentication, and literal wildcard handling.

## Cited answering milestone
POST /api/chat with {"question":"What was said about UAT?","theme_id":"office"}. Returns per-claim source IDs and source objects with evidence, titles, event dates, origin, and source URLs. Optional theme restricts retrieved knowledge. Empty retrieval skips Gemini and returns no_evidence. Invalid or missing citations fail closed with 503.

Retrieval currently uses keyword overlap in active knowledge, not embeddings or full-transcript search. Corrected records are retrieved by current text rather than old evidence. Up to 200 recent candidates are considered and 12 provided to Gemini. This is a first answering endpoint, not the completed semantic-search MVP. It does not route pending-action questions automatically; use GET /api/actions for reliable structured action lists.

Citation validation checks that cited IDs were supplied to the model, not semantic entailment or factual accuracy. Review source content and correction history. Live Gemini remains untested. 19 automated tests pass against SQLite with simulated providers.

## Quality safeguards
New text submissions are deduplicated by trimmed exact text, selected theme and UTC-normalized event timestamp (title does not affect identity). Matching submissions return HTTP 200 with duplicate:true and the existing ID; new entries return 201 with duplicate:false. Missing timestamps mean identical text in the same theme is treated as a duplicate. Supply a distinct event time for repeated conversations. This is exact-content detection, not semantic similarity.

Migration 0004 fingerprints one canonical entry per existing duplicate group without deleting or modifying the others. Existing test duplicates remain searchable. Previously extracted objects are not reclassified automatically.

Extraction prompt v2 distinguishes proposals from commitments. A tentative ownerless action is conservatively converted to a tentative decision. Date basis is explicit, relative, inferred or unknown. Inferred/unknown dates are not persisted as concrete deadlines. Bare weekday references should retain the weekday in text, leave due_date null and mark date_basis inferred. Semantic correctness still requires review. User-specified due-date corrections are marked explicit and audited.

23 automated tests pass, including canonical timestamp deduplication, event distinction, date guards and preservation of legacy duplicate records. Live prompt quality needs verification after deployment.
