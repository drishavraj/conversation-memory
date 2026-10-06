# Phase 4: persistent, scoped chat backend

## Development deployment

Deploy the development web service from this commit. The existing startup command runs additive migration **0008**, creating `memory_chat_threads` and `memory_chat_turns`. Verify migration success and a healthy service. No new environment variables or worker deployment are required. Keep `MEMORIES_ENABLED=true` in development. Production is not promoted by this change.

The existing single-question UI remains unchanged. It does not create saved threads. The Chats/history/composer UI and streaming presentation are Phase 5. These endpoints currently return the completed structured response in a normal HTTP request, not an SSE stream.

## API contract

All endpoints require existing owner authentication/MFA rules and the Memories feature flag.

- `POST /api/memories/chats`: create with `project_id`, optional `topic_id`, optional `title`. Returns ID and `version=0`. Scope is immutable.
- `GET /api/memories/chats`: global recent history; optional `project_id`, `topic_id`, `q`, `offset`, `limit` (default 30, maximum 100). Search title, project or topic name. Returns `items` and `has_more`.
- `GET /api/memories/chats/{id}`: thread metadata and newest turns in chronological order; `limit` and `before` (sequence) page into older turns. Returns `has_older`.
- `PATCH /api/memories/chats/{id}`: rename with `title` and `expected_version`; cannot move scope. Rejects stale or busy updates.
- `POST /api/memories/chats/{id}/turns`: `question`, `expected_version`, new UUID `request_id`, optional `include_history`. Returns `thread_version` and `turn`.
- `POST /api/memories/chats/{id}/turns/{turn_id}/retry`: explicitly retry the latest failed/expired turn, preserving question, request ID and saved model. Completed turns are returned unchanged.

A turn contains the user question, status (`running`, `completed`, `failed`), frozen provider/model, timestamps, context metadata, and response (claims, citation snapshots and source evidence). A completed response can be `answered` or `no_evidence`. Failed generation returns a stored failed turn, rather than losing the user's message. Inspect `turn.status`, not HTTP success alone.

The same request UUID and content returns the existing turn, including when still running. Reusing the UUID with different content returns 409. A thread allows one in-flight response. A failed turn must be retried before sending a follow-up; users can instead start a separate thread. Interrupted requests are recoverable after a 15-minute lease; GET exposes `retry_after_seconds`. Clients should poll the saved thread after a connection timeout instead of generating a new request UUID. A newer retry invalidates the older execution lease so a late response cannot overwrite it.

## Context and evidence rules

- Retrieve accepted memories only inside the immutable project/topic scope. No other chat threads enter the prompt. Project-wide questions require a new project-scoped thread.
- Supply the last 12 completed turns plus up to 20 older, explicitly truncated excerpts. Metadata reports omitted turns. This is bounded context, not exhaustive recall or a generated semantic summary.
- Previous assistant text is conversational context only; every factual claim must cite a current supplied memory. When a prior answer's evidence is stale, omit its assistant text from follow-up context. Preserve user questions as untrusted reference material.
- Retrieve up to 500 recent accepted memories, select up to 40 by question and recent-question terms, and cap record context at 80,000 characters. Pending changes are capped at 10 compact excerpts. Context limits are reported. This remains bounded project retrieval, not unlimited semantic chat recall.
- Revalidate cited memories after generation. A changed source prevents publishing the new answer and produces `sources_changed_retry`.
- Store old answers and evidence immutably. Reading a saved turn adds `changed_source_ids` computed against current data without modifying its historical response. Follow-up context metadata also reports prior evidence changes.
- Chat text never automatically updates project memories, completes tasks, or becomes evidence.

## First manual check in development API docs

1. Use a project/topic with an accepted memory. Copy its IDs from Memories endpoints.
2. Create a thread with `POST /api/memories/chats` and copy its ID.
3. Send a turn using the returned version and a fresh UUID, for example `057c8926-3a71-4f9c-a02f-2f3769468784`. Ask a question supported by that memory.
4. Read the thread with GET. Confirm the saved question, response and citations.
5. Send a follow-up using the latest `thread_version` and another UUID. Confirm its scope stays fixed.
6. Create another thread under the same topic. Its initial context should be empty.
7. Repeat the original POST with its original UUID/content: it must return the original turn without another model call.
8. Use the global history endpoint to find and reopen both threads. After a source correction, confirm an old turn retains its answer but exposes changed source IDs.

Automated coverage includes owner/feature gates, wrong-topic rejection, immutable scope, independent thread context, duplicate submissions, stale versions, in-flight conflicts, invalid citations, provider failure/retry, frozen models, source changes during generation, immutable snapshots, expired lease recovery, bounded context, history pagination, and migration rollback/re-upgrade preserving existing memories. Providers are mocked; live provider follow-up quality and production PostgreSQL rollout still require development validation.
