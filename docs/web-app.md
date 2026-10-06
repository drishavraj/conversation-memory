# Web app and MFA setup

The mobile-first web app is served at the root of the existing FastAPI service. Docker builds its bundled JavaScript with Node, then serves the assets with Python. There is no additional frontend hosting service or CORS configuration. Conversations, files, processing and search stay in the existing Render PostgreSQL database and worker. Supabase is used only for identity.

## One-time setup

1. Create a Supabase project at https://supabase.com/dashboard. The hosted provider provisions a database, but this application does not store memories there. You can alternatively deploy compatible Supabase Auth yourself.
2. In Authentication settings, disable public signups. Keep email/password authentication and TOTP MFA enabled.
3. Under Authentication → Users, create the owner's user with their email and a strong password. Use the dashboard to confirm the email when creating this initial account. Copy the user's UUID.
4. Under the project's connection/API settings, copy the Project URL and **publishable** key (or legacy `anon` key). Never use a secret or service-role key here. Use an asymmetric JWT signing key (ES256 or RS256). Legacy HS256 JWT signing is not supported by this backend; migrate/rotate to the project's asymmetric signing key before testing.
5. In Render **conversation-memory-api2 → Environment**, add:

   | Variable | Value |
   | --- | --- |
   | `SUPABASE_URL` | Project URL, such as `https://your-project.supabase.co` |
   | `SUPABASE_PUBLISHABLE_KEY` | Publishable key |
   | `AUTH_OWNER_USER_ID` | Owner user's UUID |
   | `ALLOW_OWNER_API_TOKEN` | `false` |

   Keep existing database and Gemini configuration. These four variables are needed only on the API service, not on the worker. The worker keeps its existing owner token configuration. Save and redeploy. Keep Docker Command blank so Docker uses `/app/start.sh`.
6. In Supabase Authentication URL configuration, set Site URL to the API's actual HTTPS base URL and allow the exact redirect `https://YOUR-RENDER-HOST/?recovery=1`. Configure SMTP for reliable password-reset email delivery. Do not use broad wildcard redirects in production.
7. Open the API's base URL without `/docs`. Sign in, choose **Set up authenticator**, scan the QR or enter the setup key, and verify a six-digit code. Subsequent logins ask for the authenticator code.

## Verification

- Open Record → Text and save a note in Office. Open Conversations and wait for processing. Use Ask your memory and open a citation. Complete a to-do from the home screen.
- Sign out and sign in again: an authenticator code is required.
- A password-only token must receive 403 from private endpoints. A different user's token must receive 403 even after MFA. Missing/invalid/expired tokens receive 401.
- When browser authentication is fully configured, static owner-token authentication is disabled by default. Explicitly set `ALLOW_OWNER_API_TOKEN=false` to keep this clear. Existing Swagger requests with that token will then stop working. Never set this variable to true for a deployment that requires MFA for all API access.
- Initial deployments without Supabase configuration keep the existing token-based API behavior but show a setup screen at `/`. This is not an MFA-enabled deployment yet.

## Phone use

Open the HTTPS base URL in Safari and use Share → Add to Home Screen. The app has a manifest and responsive bottom navigation. Recording requires microphone permission and browser MediaRecorder support; uploading an audio file is the fallback. The application needs a network connection and does not cache private memories offline. A native home-screen widget is not included.

## Recovery and security limits

Password reset uses Supabase's email flow and still requires MFA for private data. This version does not implement recovery codes or self-service MFA removal. If the owner loses their authenticator, the Supabase project administrator must verify ownership and remove the lost factor through the provider's administrative tools. The owner then signs in and enrolls a new authenticator before the API allows access. Keep access to that administrative account separately protected.

JWT verification checks signature against the configured project's JWKS, issuer, audience, expiry, role, owner UUID and `aal2`. Short-lived access tokens can remain valid until expiry after logout/revocation; configure a suitably short access-token lifetime in Supabase. JWKS requests are cached by PyJWT. Only publishable configuration is exposed to the browser. User text is escaped before rendering, private API responses use `Cache-Control: no-store`, and the app uses a Content Security Policy. Browser sessions are managed by the Supabase SDK; avoid using a shared or untrusted device.

Conversations supports case-insensitive title/transcript search across entries, scoped to the selected theme, in pages of 20. Actions show up to 100 records per theme/status and say when this limit is reached. It does not yet include action pagination, chat history, self-service second-factor management. Due dates are shown as absolute calendar dates. Corrections use the backend's version checks and audit trail.

## Local development

```sh
cd frontend
npm ci
npm run build
cd ..
python -m alembic upgrade head
uvicorn app.main:create_app --factory --reload
```

Configure the same variables locally and allow the exact localhost reset redirect in a development Supabase project. Run `python -m pytest -q` for backend checks. The browser smoke check uses mocked API and authentication responses; live provider enrolment and reset-email delivery require verification after configuration.

To run the mocked browser smoke check, use a development server with `SUPABASE_URL=https://example.supabase.co`, `SUPABASE_PUBLISHABLE_KEY=sb_publishable_test`, and `AUTH_OWNER_USER_ID=owner` so its CSP permits the mocked provider origin. Install the browser with `npx playwright install chromium`, then run `node tests/smoke.cjs` from `frontend`. Set `UI_BASE_URL` if the server is not on port 8000. This test checks navigation, citations, corrections, phone width, and the password/MFA gate using fake responses; never use these fake settings in production.

## Minimal interface

The app opens on **To-dos**, grouped into Overdue, Today, Upcoming, No date, and Tentative. Grouping uses the device's local calendar date and does not invent dates for undated tasks. Tap a task to expand its evidence and correction controls. Completion, dismissal, and reopening use the existing version-checked API. Pending/failed entries among the latest 100 conversations are surfaced below the task list.

The three navigation destinations are **To-dos · Record · Conversations**. Ask your memory is inside Conversations. The top-right Settings button contains **System / Light / Dark** appearance and expandable AI model defaults. Appearance is stored on the current browser/device; System follows operating-system changes.

Record opens directly in audio mode. Choose a theme, record, pause/resume, finish, listen back, and save. Uploads and text capture remain available. Title/date and AI choices are expandable. A blank title receives a simple theme/date title; this is not AI title generation. Model defaults and per-entry selections retain their existing behavior.

Leaving the recording screen prompts before discarding captured or active audio. Reload/close protection uses the browser's beforeunload event, which mobile browsers may not honor when the app is killed. Unsaved audio stays in memory, not durable offline storage. Keep the app open while recording and save before switching away. Background/locked-screen recording is not guaranteed. Verify microphone access, pause/resume, playback, and saving on your actual phone.

This update needs no new environment variables or database migration. Deploy the development web service to receive the UI and conversation-search query support; the worker needs no changes for the redesign.
