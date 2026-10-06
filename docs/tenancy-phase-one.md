# Tenant foundation: Phase 1 expansion

This candidate adds database ownership to the existing single-owner application.
It does NOT authorise multi-user access. Do not enable public signup or invite testers yet.

## Implemented

Migration 0009 creates workspaces, memberships and workspace AI settings. It adds
non-null, indexed workspace_id to all 15 source/derived/job/chat tables. Existing
records keep their IDs and content and are assigned to the legacy private workspace.
AUTH_OWNER_USER_ID, if provided, must be the verified existing owner's Supabase UUID;
it is recorded as the active owner membership. No first-signup claim is permitted.
Without that setting, the workspace is explicitly unclaimed and gets no membership.
This does not change the existing owner-authenticated API in this phase.

Relational links are constrained to the same workspace. PostgreSQL uses composite
foreign keys; SQLite uses relationship triggers because rebuilding referenced parent
tables during a live migration with foreign keys enabled is unsafe. Existing global
IDs and single-owner API behaviour are retained.

AI settings are copied to workspace_ai_settings. The current application continues
using ai_settings until Phase 2 switches reads/writes to authenticated workspace
settings. Do not edit the new copy independently before that cutover; Phase 2 must
resynchronise the legacy defaults once, transactionally, before switching.

A server/ORM default sends legacy writes to the original workspace during this
single-owner transition. It MUST be removed in Phase 2, after every request and worker
supplies workspace identity. It is not an isolation or authorization mechanism.

## Remaining enforcement work (Phase 2 prerequisites)

- Scope all APIs, retrieval, worker jobs, file access, caches and idempotency.
- Remove legacy workspace defaults and unrestricted owner-token multi-user access.
- Scope formerly global fingerprint/project-name uniqueness by workspace. These
  stronger legacy uniqueness restrictions remain during single-owner compatibility.
- Validate JSON references (topic arrays, evidence, proposal targets, saved response
  snapshots and pending-turn IDs); SQL foreign keys cannot validate embedded IDs.
- Configure a restricted PostgreSQL runtime role, separate migration credentials,
  transaction-local workspace context and ENABLE/FORCE row-level security policies.
  RLS is deliberately NOT enabled by 0009: current requests/workers lack context and
  would stop working. No role or credential is automatically created by this code.
- Test pooled-connection context cleanup, worker tenant isolation and two-user access.

## Deployment and verification

1. Back up development and confirm it is a different database from production.
2. Verify AUTH_OWNER_USER_ID is the existing owner's UUID in the development web
   service environment before deploying. Migration reads it from the process
   applying migrations. Never substitute a new tester's ID.
3. Deploy development web, let start.sh apply 0009, then deploy the compatible worker.
4. Run `python -m app.workspace_audit` in the development web Shell. Check ok=true,
   zero unclaimed workspaces and zero invalid_workspace counts. Counts contain no
   transcript text, tokens or user IDs.
5. Confirm login/MFA, old conversations/files, a new upload, worker processing,
   to-do changes and saved memory chats still work.

If the workspace is unclaimed, do not open onboarding or bind it to the next login.
Resolve the original owner through a separately reviewed administrative operation.

## Validation

SQLite migration tests verify legacy content/IDs, membership binding, AI settings
copy, default compatibility, cross-workspace write rejection, non-null ownership,
workspace deletion rejection, absent-owner quarantine and invalid-owner fail-fast.
Existing backend regression suite also passes.

PostgreSQL validation remains pending: this environment could not install a server.
To rehearse against an EMPTY DISPOSABLE PostgreSQL database (not dev/prod), set
TENANCY_TEST_DATABASE_URL to its URL, then run:

    python -m pytest tests/test_workspace_foundation.py -q

The fixture refuses a nonempty database and leaves the PostgreSQL fixture for
inspection. Use a fresh disposable database for each run. This test verifies migration
and constraints, not RLS or application tenant isolation.

## Recovery

0009 deliberately rejects automatic downgrade: dropping ownership columns would
remove tenant boundaries. Old compatible application code can run against the added
columns during this phase. Restore a verified backup only through an intentional
recovery procedure. Production promotion waits for the PostgreSQL rehearsal and
live development checks. Phase 1's expansion is implemented; full database enforcement
and the Phase 2 application cutover must be completed before multi-user onboarding.
