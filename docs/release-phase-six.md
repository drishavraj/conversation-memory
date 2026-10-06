# Phase 6: development release candidate

Production promotion is pending the live development checks below.

## Changes

- Keep the Expand chat / Return to pane label correct after a reply or polling refresh.
- Capture each citation dialog in its own close handler, so closing an old dialog cannot remove a newer one.
- Prevent a slow New chat request from opening its result after the user has navigated to another view.
- Add an opt-in browser integration test against the actual FastAPI server, migrated database and HTTP/SSE routes. External identity and model generation are deterministic test doubles. It uses a synthetic owner token explicitly enabled only in the test; it does not validate live Supabase authentication.

## Automated checks

Validated on 6 October 2026:

- 83 existing backend tests passed.
- New real-HTTP browser integration passed: migrate SQLite to head, create a scoped chat, follow up with thread context, keep expanded state after replies, inspect citations, reload saved history, and check 390px/320px widths.
- 14 frontend unit tests passed, including stream interruption, UTF-8 framing, progress checkpoints and collision-free map layouts up to 100 nodes.
- Frontend production build passed.
- Existing browser journeys passed: memory project/topic creation, source linking, proposal acceptance, chat history/follow-ups/retries, recording/upload, action updates, citation/correction dialogs, mobile layout and MFA gating. These journeys mock external services and some API routes.

Run locally (install requirements-dev.txt and frontend dependencies first):

```sh
npm --prefix frontend run build
cd frontend
npx playwright install chromium --only-shell
cd ..
RUN_RELEASE_BROWSER=1 python -m pytest -q
node --test frontend/tests/chat-events.test.mjs frontend/tests/processing-progress.test.mjs frontend/tests/memory-map.test.mjs
```

The opt-in test is skipped in ordinary backend-only runs. It requires Node, Playwright's browser and built app/static assets. Browser tests do not measure real-phone animation performance, keyboard safe areas, live AI answer quality, Render streaming or PostgreSQL migration behaviour.

## Deploy and test development

1. Deploy the development web service from the Phase 6 develop commit. Verify the deployed commit in Render. The Docker build compiles frontend assets. The existing start.sh applies Alembic migrations before serving traffic; confirm migration 0008 is applied on the development database. This phase adds no migration.
2. Keep the development worker on the same candidate commit. This phase requires no new worker task or environment variable. Check that both development services still use the development database and intended provider settings. Keep APP_ENV=development and MEMORIES_ENABLED=true in development.
3. Sign in with real MFA. Confirm Record, To-dos and Conversations work. Record a short synthetic conversation, submit it, watch the processing steps, then complete an action without a whole-page refresh.
4. Open a project/topic in Memories. Check Map/List parity, source links, proposal review and the current accepted knowledge. Use one real pilot project to assess whether updates and citations are correct. Avoid bulk archive backfill until the pilot is accepted.
5. Ask a supported question, then a follow-up. Expand the pane and send another message; Return to pane must remain available. Open and close citations. Reload, open Chats directly, and resume the saved thread.
6. Start a second chat on that topic. Confirm it is independent. Select another topic and confirm the previous chat retains its original scope. Ask across project must create a new broader discussion. Rename a thread and find it in global history.
7. On a synthetic question, briefly disconnect after sending. Reconnect, reopen the saved chat and check its status before retrying. There should be one saved submission. Confirm progress arrives through Render and the final cited answer appears. Progress streaming is not token-by-token model output.
8. On a physical phone, test light/dark mode, reduced motion, long labels, map/list navigation, microphone permission, save CTA visibility, the keyboard/composer and citation dialogs. Check desktop keyboard navigation and visible focus. Measure animation smoothness on the target device; no 60fps claim has been verified.
9. In development, set MEMORIES_ENABLED=false and redeploy the web service; Record, To-dos and Conversations should remain usable. Restore true after the check.

Record the candidate commit, device/browser, pass/fail and any issue for each check. Note answer latency, provider usage/cost, incorrect memory updates and rejected proposals during the pilot; automated product telemetry and a labelled live-provider evaluation set are not included in this phase.

## Production promotion and recovery

After the development checklist passes, open a develop → main PR and merge the reviewed candidate. Deploy production web and worker from the same main commit. Production must retain its own database, Supabase project, owner ID, provider secrets and APP_ENV=production. Do not copy the development environment group into production.

Before promotion, confirm a current production database backup and the migration path on development PostgreSQL. Check web startup migration logs, then login/MFA, recording, one to-do update, Memories and a saved chat on production.

For a Memories/Chats issue, disable MEMORIES_ENABLED on the production web service and redeploy while investigating. If needed, redeploy the last known-good compatible web/worker commits. Do not downgrade/drop memory or chat tables as a routine rollback; retain source data and saved history. No production deployment has been performed by these automated checks.
