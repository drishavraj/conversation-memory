# Task-specific AI settings

Configure defaults under **Settings** after signing in with MFA. Choose a model independently for transcription, English translation, summary, memories/decisions/actions extraction, and answers. In **Capture → Processing options**, select expected languages and override models for that entry. Text and document inputs skip transcription. The existing Record audio button uses the same processing choices as an uploaded file.

## Development rollout on Render

1. Deploy the `develop` branch to the development API and worker. The API's existing startup command runs migration `0006` automatically. Wait for the API migration to finish before starting/restarting the new worker. If the worker started earlier and logged missing-column/table errors, restart it after the API is live.
2. Keep `GEMINI_API_KEY`, `GENERATION_MODEL`, and `EMBEDDING_MODEL` at their current working values in `memory-dev-shared`. No variable named `GEMINI_MODEL` is needed.
3. Set `APP_ENV=development` in that group to show the test-environment banner.
4. Optionally add `OPENAI_API_KEY` and/or `SARVAM_API_KEY` to that group. Link the group to both development services and deploy both with the updated environment. Only add credentials for providers you intend to use. Never put provider keys in Git, Supabase public settings, browser code, or chat.
5. Keep the development Supabase URL, publishable key, allowed owner UUID, and authentication configuration on the API. They do not need to be added to the worker for this feature.
6. Open the development app, sign in, select **Settings**, and save defaults. Providers without a configured key have disabled model options. Key presence is not a live access check.
7. Submit a short test recording, choose English/Hindi/Marathi as appropriate, and inspect **Library → entry → Processing details**. Verify the transcript, translation, summary, action owners, dates, and evidence. Test each newly enabled provider before relying on it.

Keep production on its existing release while testing. Production can later have its own `memory-prod-shared` group linked only to production services. Each environment has its own credentials, database, and saved defaults. Do not link dev and production to the same group or database.

## What is stored where

| Setting | Storage | Change method |
| --- | --- | --- |
| Provider API keys | Server environment / Render group | Update the group and redeploy affected services |
| Default provider and model for each task | Application PostgreSQL database | Settings screen; no deploy needed |
| Models and expected languages for a new entry | Entry's saved processing configuration | Capture → Processing options before submission |
| Completed task outputs | Application PostgreSQL database | Worker checkpoints; reused on retry |
| Embedding model | `EMBEDDING_MODEL` environment variable | Operator change plus reindexing |

Before defaults are first saved, all tasks use Gemini and `GENERATION_MODEL`. Optional bootstrap overrides are `TRANSCRIPTION_PROVIDER`/`TRANSCRIPTION_MODEL`, `TRANSLATION_PROVIDER`/`TRANSLATION_MODEL`, `SUMMARY_PROVIDER`/`SUMMARY_MODEL`, `EXTRACTION_PROVIDER`/`EXTRACTION_MODEL`, and `ANSWER_PROVIDER`/`ANSWER_MODEL`. Provider values are `gemini`, `openai`, or `sarvam`, subject to supported task capabilities. These are fallbacks: saved database defaults take precedence. Most installations should use Settings instead of adding these variables.

`GEMINI_MODELS` can add comma-separated Gemini IDs to the catalog. Include only models you have verified support this app's structured `generateContent` calls and audio input. The catalog does not query billing, account access, pricing, or model lifecycle. OpenAI and Sarvam choices are explicitly listed in the adapter catalog; adding an arbitrary model name is not sufficient to implement a new provider or capability.

## Supported adapters

- Gemini: audio, translation, summary, extraction, and answers; existing Gemini API integration.
- OpenAI: `gpt-4.1-mini` / `gpt-4.1` for structured text through Responses with `store:false`; `gpt-4o-transcribe` / `gpt-4o-mini-transcribe` for audio. This adapter accepts MP3/M4A/WAV/WebM up to 25,000,000 bytes. Speaker names are not inferred.
- Sarvam: `saaras:v3` / `saaras:v4` for asynchronous batch transcription, with speaker labels. Mixed selected languages use codemix mode. One selected language supplies a language hint; no selection allows detection. The app's 25 MiB audio cap still applies. Batch jobs persist their remote ID and resume polling without holding up the worker between polls.

Language choices are hints, not accuracy guarantees. Speaker labels do not identify people; review owners in extracted actions. Provider access and multilingual quality require live tests with your account and representative recordings.

Transcription, translation, summary, and extraction are separate calls. Summary and extraction each receive the original source, preserving original-language evidence. Separate calls can increase latency and cost. Choosing multiple providers sends the relevant source to each selected provider. Answers use retrieved records and the answer default active when the question is asked. Semantic search remains Gemini-based and environment-managed; it must use the same embedding model as its stored vectors.

## Retries and existing entries

Model selections are frozen when an entry is created. Changing defaults affects new entries, and answer defaults affect the next question. Retrying a failed entry keeps its models and skips completed stages. No silent fallback to a different provider occurs. An explicit retry after a failed/expired Sarvam remote job creates a fresh remote job; transient errors resume the saved job. Provider job creation cannot be atomic with the local database, so a crash between remote creation and saving its ID can leave a remote job behind.

Existing queued entries without a snapshot acquire one when first processed. Already processed entries retain their existing content and corrections. Completed entries cannot yet be reprocessed with a new model. Uploading the same content with the same theme and event time returns the existing entry, even if model choices differ; it does not overwrite or charge for another processing pass.

Provider-side data retention depends on each provider and account settings. Sarvam job artifacts are not explicitly deleted by this adapter. Gemini temporary file cleanup remains best-effort. `store:false` is not a guarantee of zero retention at OpenAI.

## Tests

Run `python -m pytest -q`. Tests use isolated databases and mocked HTTP contracts, including frozen selections, checkpointed retries, provider-key redaction, batch resume, and signed storage requests without provider credentials.

Build the UI with `cd frontend && npm ci && npm run build`. With a local API serving the built UI and `SUPABASE_URL=https://example.supabase.co`, `SUPABASE_PUBLISHABLE_KEY=sb_publishable_test`, and `AUTH_OWNER_USER_ID=owner`, run `UI_BASE_URL=http://localhost:8000 node tests/smoke.cjs` from `frontend` after `npx playwright install chromium`. Browser tests mock authentication and AI endpoints; they do not use real recordings or provider keys. They cover settings persistence, per-upload choices, mobile layout, existing navigation, and MFA gating.
