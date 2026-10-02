# Conversation Memory

An Apache-2.0, self-hostable conversation-memory backend. One owner per installation. Lovable UI/PWA and browser-session login are planned; current interaction is through FastAPI /docs using a private owner bearer token.

## Features
Text capture; audio and TXT/DOCX/text-PDF upload; original source download; English translation; summaries; evidence-backed memories, tentative decisions and actions; Personal/Side Projects/Office themes; corrections with audit history; action completion; exact duplicate prevention; background processing; optional hybrid keyword/semantic retrieval and cited answers.

## Local setup
Requires Docker Compose. Copy .env.example to .env and set independent long random database password and owner token. Use URL-safe database passwords; never commit credentials. Set GEMINI_API_KEY and GENERATION_MODEL to available Gemini models. Optional EMBEDDING_MODEL enables semantic indexing/search.

```sh
docker compose up --build -d
# Enable continuous AI processing once credentials are configured:
docker compose --profile processing up --build -d
```

The start script runs migrations, then serves on PORT or 8000. Visit http://localhost:8000/docs and Authorize with OWNER_API_TOKEN (without Bearer prefix). PostgreSQL and Redis ports are not exposed. Redis remains in local Compose but the current worker uses durable PostgreSQL job records.

## Deployment and testing
- [Automatic processing](docs/automatic-processing.md)
- [Audio, documents, semantic search, limits and Render setup](docs/media-and-semantic-search.md)

Render uses one Docker web service, PostgreSQL, and a separate Docker Background Worker with command `python -m app.worker --loop`. Copy the same DATABASE_URL, GEMINI_API_KEY, GENERATION_MODEL and optional EMBEDDING_MODEL into the worker. Docker Command for the API may remain blank; Dockerfile startup runs migrations. Run only one continuous worker initially.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

40 tests pass on isolated SQLite databases with mocked AI/HTTP services. Text ingestion, Gemini extraction, cited keyword chat, theme isolation, action completion and automatic processing were verified live separately. New audio and semantic features need live verification.

## Important limitations
- Audio max 25 MiB; documents max 10 MiB and 200,000 parsed characters. OCR unsupported.
- Private file bytes are stored in PostgreSQL for this bounded personal MVP; use object storage for larger archives.
- Vectors use exact Python cosine scoring over JSON storage, not an approximate pgvector index; intended for personal-scale datasets.
- No reminders, shared accounts, browser login, UI, or autonomous external actions yet.
- Theme labels organise content; owner authentication protects access. Theme labels do not implement team permissions.
- AI extraction and citation IDs cannot prove factual correctness. Review sources and corrections.
- Failed jobs require explicit retry. After confirming old workers are stopped, --recover can requeue processing claims older than 15 minutes. No automatic retry charges.
- Existing duplicate source records are retained. New matching ingestion returns HTTP 200 duplicate:true; new entries return 201 duplicate:false.

Keep personal data, recordings, tokens and database backups out of Git. Configure paid AI billing and hosting privately. See SECURITY.md and CONTRIBUTING.md before publishing real data or contributions.


## Mobile web app, login and MFA

The API now serves a mobile-first web app at `/`, with Capture, Ask, Library, and Actions. Personal, Side Projects, and Office are labelled throughout. Email/password login and mandatory authenticator-app MFA use Supabase Auth; the API validates signed tokens, MFA assurance, and the single allowed owner. Memories remain in the existing database. See [web app setup](docs/web-app.md) for the four Render environment variables, provider configuration, recovery limits, phone installation and local development.

The Docker build bundles the frontend automatically. An unconfigured deployment shows a setup screen, and keeps its existing API-token behavior until browser auth is configured. Once configured, owner-token access defaults to disabled; set `ALLOW_OWNER_API_TOKEN=false` explicitly to enforce this. Password reset is available, but self-service MFA recovery codes are not implemented.
