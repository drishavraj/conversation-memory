# Audio, documents, and semantic search

## Supported inputs
POST /api/entries/upload is authenticated multipart upload. Select a file in /docs; optional title, theme_id and event_at (ISO timestamp with timezone) are form fields. Leave optional values blank rather than Swagger placeholders. Limits: 25 MiB for MP3/M4A/WAV/OGG/FLAC/WebM audio, 10 MiB for TXT/DOCX/text-based PDF. Extension plus common format signatures are checked; actual decoding/parsing can still fail. UTF-8 TXT, DOCX paragraphs/tables, and PDF text extraction are supported. Encrypted/scanned PDFs and OCR are unsupported. Documents max 100 PDF pages and 200,000 extracted characters. DOCX expanded ZIP content is capped at 30 MiB.

Original bytes are stored privately in PostgreSQL so the API and separate Render worker share them without a filesystem volume. GET /api/entries/{id}/file downloads the original with owner authentication. This bounded-storage strategy is for an early personal deployment: uploads grow database usage and backups; large collections should move to private object storage. Exact file-byte hash, extension, theme and event timestamp deduplicate reuploads. There is no cross-channel or semantic deduplication.

Worker states: transcribe or parse, then normalize/extract. Parsed text/transcription is committed before extraction, so explicit retries reuse it. Gemini Files API receives audio temporarily; cleanup is attempted in finally on success/failure. A process killed mid-request can leave a temporary file until provider expiry. Source evidence references the saved transcription, not proof of transcription accuracy. Speaker identities remain model estimates; no accurate word-level timestamps or duration metadata is promised. Both transcription and extraction use GENERATION_MODEL (the tested deployment uses gemini-3.8-flash). Audio is not tested live yet.

New entries preserve the supplied event timezone in event_local for relative date interpretation. Older entries have only UTC timestamps; relative dates near midnight may need manual review.

## Semantic configuration on Render
1. Wait for API migration 0005 to complete and API/worker deployments to be Live.
2. Add EMBEDDING_MODEL=gemini-embedding-2 to BOTH API and Background Worker environments, saving/redeploying each. This is a documented model name, but availability must be checked for your account if HTTP 404 appears. Keep GENERATION_MODEL unchanged.
3. Existing ready entries with pending index_status are backfilled automatically by the worker, one vector at a time. Source text is chunked with character offsets; knowledge records are indexed separately. This makes additional paid embedding requests. Entry status remains ready while index_status is pending/ready/failed.
4. POST /api/entries/{id}/index/retry requeues failed indexing or reindexes after an embedding-model change. It never retranscribes the audio.
5. POST /api/search/semantic with {"question":"What is blocking launch?","theme_id":"office"} returns hybrid retrieval records. POST /api/chat uses the same hybrid retrieval and source validation automatically when configured. Existing GET /api/search remains literal keyword-only.

Embeddings are 768-dimensional normalized vectors. This implementation stores JSON vectors and computes exact cosine similarity in Python for personal-scale collections, rather than requiring a pgvector extension or approximate index. It scans the selected model's indexed corpus; latency/memory grow with corpus size. A future pgvector index can replace the scorer without changing capture or answering APIs. Relevance threshold defaults to 0.6 and needs calibration on real questions. Keyword and semantic ranks are fused; corrected/dismissed/completed knowledge vectors are ignored when stale or inactive.

Full-transcript chunks use the primary entry theme. Scoped retrieval excludes chunks from entries whose extracted item themes reveal mixed or unknown classification; All scope can search them. Theme labels are organisation metadata, not multi-user security boundaries. Corrections take precedence in the answering prompt, but old original-source text is retained for historical evidence. Citation checks validate source IDs, not semantic entailment.

If embeddings fail, keyword matches can still answer with an explicit warning. Without keyword evidence, retrieval returns 503 rather than pretending the corpus contains no answer. If EMBEDDING_MODEL is unset, existing keyword chat continues normally. Switching embedding models requires reindexing; vectors from different model names are never compared.

## Live acceptance tests
- TXT: upload a synthetic conversation; wait for ready; original_text matches file and file download preserves bytes.
- DOCX/PDF: inspect extracted text, summaries, and evidence. A scanned PDF should fail with no_text_found_ocr_not_supported.
- Audio: upload a short Hinglish recording, compare original_text with speech, then inspect English text and extracted items.
- Semantic: with index_status ready, save 'Production credentials are pending' and ask 'What is blocking go-live?' in matching theme. Check hybrid mode and source citations; quality is model-dependent.
- Theme: the corresponding unrelated scope must not return those knowledge records.
- Correction: edit a memory; old vector is immediately excluded, updated vector appears after reindexing.

40 automated tests pass with SQLite and simulated Gemini/embedding providers. Tests include upload validation, parsing real text PDFs/DOCX, transcription reuse, Files API cleanup, vector validation, no-keyword semantic matches, theme isolation, stale-vector exclusion, indexing failures and cited hybrid answers. Docker, audio model quality, live embeddings and production-load performance still need verification.
