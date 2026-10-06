# Memories v1 — development rollout

This release connects the approved cloud concept to real project data. It is guarded by `MEMORIES_ENABLED` (default `false`). It does not move or rewrite existing conversations automatically.

## Enable in development

1. Keep the development database separate from production. Take a database backup before migrating an existing environment.
2. Deploy the development web service from the new `develop` commit. The existing `start.sh` runs Alembic; confirm migration `0007` and a healthy service. The migration only adds tables.
3. Deploy the development worker from the same commit.
4. Set `MEMORIES_ENABLED=true` in `memory-dev-shared`, linked to both services, and deploy both with the updated environment. If the group automatically redeploys them, wait for both deployments to become live.
5. In Settings, check **Memory organisation**. It uses existing provider adapters and keys. `RECONCILIATION_PROVIDER` and `RECONCILIATION_MODEL` are optional initial defaults; queued jobs freeze their model choice. A retry keeps that choice. Configure it before linking conversations.
6. Reload the dev app. A new **Memories** destination appears. Production stays unchanged until a later explicit promotion and flag enablement.

## First real project

- Create PNB Edge under Office; add topics such as MVP and Demo.
- Open the project or a topic, choose **Link a conversation**, search Office entries, select the desired topics, and save. One conversation may be linked to several projects within its theme. Multiple topics are supported without duplicating a canonical memory.
- The worker waits for conversation processing to finish, then creates memory suggestions. Linking is explicit; the model is told to ignore knowledge unrelated to the chosen project.
- Use Refresh, or wait for the project overview to refresh. Open **Review suggestions**. Inspect source quotes, change the proposed text if needed, explain the review, and accept or reject it.
- Accepted memories appear in the project/topic view. History shows reviewed revisions and allows restoring an earlier version if its sources remain valid.
- **Ask about this** answers from accepted memories within the visible project/topic scope. Enable **Include memory history** for change questions. Answers have memory citations and original conversation evidence.
- Record/upload can optionally select a project. This links the saved entry without assigning topics. Link failure never discards the saved conversation; it can be linked from Memories later.

## Behaviour and limits

- All AI additions, supporting evidence, replacements and conflicts require review in v1. Nothing silently overwrites accepted knowledge. Exact accepted duplicates combine their evidence under the project lock.
- Actions still use the existing To-dos workflow. This release does not automatically complete tasks from later speech. Corrections or action-status edits change the source version; affected memories are excluded from answers until valid evidence is accepted again. Use **Regenerate suggestions** on the linked conversation.
- Unlinking leaves source conversations and revision history intact. Memories without another valid linked source are marked for review and excluded from answers. Topic membership follows the linked evidence.
- Reconciliation is a separate durable worker operation; failures do not make a ready transcript fail. Failed jobs can be retried, and expired claims can resume. Source and target versions are validated again when accepting a proposal.
- A project supports up to 100 topics; project/topic maps show 12 at a time. Accepted memories are paged in groups of 50. Linked conversations and pending-review panels show at most 100 records at a time (review pending items to expose the next batch). Link search can page through older conversations.
- Reconciliation compares a conversation's extracted knowledge with up to 200 recent accepted memories. Ask considers up to 500 recent memories, ranks by question terms, and sends at most 40 to the answer model. History includes up to 10 revisions per selected memory. This is bounded project retrieval, not a claim of exhaustive semantic recall across an unlimited archive.
- No automatic project discovery, alias merging, project renaming, topic merging, autonomous completion, proactive notifications, or multi-user tenancy in this version. The existing owner-only authentication and MFA protect every memory endpoint; themes and projects are additionally checked server-side.
- The animation is a restrained project transition with stable creation ordering and hover/focus treatment. Large-dataset performance and physical iPhone/keyboard testing remain rollout checks. The standalone design prototype remains in `docs/prototypes`.

## Verification

`python -m pytest -q` includes memory migration-backed API tests for authentication, feature flag, theme/topic scope, worker idempotency, invalid citations, source changes, unlink during generation, duplicates, reviewed history, restoration, and project-scoped answers.

From `frontend`: `npm run build`, `node --test tests/processing-progress.test.mjs`, and the Playwright suites `tests/smoke.cjs` / `tests/memories-live.cjs` against a served UI (`UI_BASE_URL`). Provider calls are mocked in automated tests; a live provider check with a synthetic meeting is required before production promotion.

Disable the flag on API and worker to hide the feature and stop new memory processing. Keep tables and evidence; do not roll back by dropping them. Re-enable after fixing the issue and reviewing queued jobs.
