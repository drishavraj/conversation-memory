# Phase 2: workspace isolation cutover

## Behaviour

The application resolves a verified Supabase MFA subject to exactly one active
workspace membership. No client-supplied workspace ID determines access. Missing,
revoked or ambiguous membership fails closed. There is no signup/provisioning endpoint
in this release; invite-only onboarding belongs to Phase 3.

Every request uses an immutable WorkspaceSession. ORM SELECT, UPDATE and DELETE
are scoped before retrieval/ranking; inserts acquire scope from the session. Scope
changes, raw SQL, administrative writes and bulk ownership/reference changes are
rejected. Embedded topic, evidence, proposal target and answer references are
validated on ORM writes. Private assets remain database-backed and downloads use
the same scoped session. Themes are a shared read-only catalogue.

Workers enumerate active workspace IDs using control-plane access, then process
normalisation, memory reconciliation, recovery and embedding jobs through separate
workspace sessions. No provider context contains another workspace's records.
SSE chat execution explicitly retains workspace and user identity in its new session.
Active membership is checked again at each new transaction for user requests.

Legacy API tokens, if explicitly enabled, access only the original workspace. Set
ALLOW_OWNER_API_TOKEN=false before tester onboarding. OWNER_API_TOKEN is still
required by the current startup configuration but is not an unrestricted access key.

## Migration 0010

- Removes the legacy workspace default from all 15 owned tables and ORM models.
- Replaces global upload fingerprints, project names and proposal fingerprint
  uniqueness with workspace-scoped constraints.
- Refreshes legacy workspace AI settings once from current deployment defaults,
  then switches application reads/writes to workspace_ai_settings.
- Enables and FORCES PostgreSQL row-level security on owned tables and workspace
  AI settings. Policies require a matching transaction-local app.workspace_id.
- SQLite rebuilds affected tables in an explicit transaction with foreign-key
  checking restored and validated before commit; existing relationship triggers
  are recreated. SQLite uses application scoping, not PostgreSQL RLS.

A normal PostgreSQL table owner is subject to FORCE RLS, but can alter policies;
superuser and BYPASSRLS roles bypass it. Therefore non-owner login on PostgreSQL is
blocked until runtime role validation confirms no superuser/BYPASSRLS, no membership
in table-owner roles, and ENABLE/FORCE RLS on all owned tables. This gate is not a
substitute for running the adversarial PostgreSQL tests.

## Development deployment order

Develop is auto-deployed. Coordinate web and worker deployment to this same commit.
Old workers cannot write rows after 0010 removes implicit workspace defaults. Stop
old worker instances during cutover if deploy timing cannot be coordinated, then
start the new worker once web startup has applied 0010. Retry affected failed jobs
only after both services show the new commit.

The existing owner can continue testing through scoped application sessions with
current database credentials. Do not invite another user yet. Run:

    python -m app.workspace_audit

Expected ownership result: ok=true. The additional runtime_isolation_ready may be
false until the restricted runtime role below is configured. invalid_memberships
now actually checks missing workspaces, invalid roles/statuses and empty subjects.
The audit enumerates existing workspaces; it is not a complete authorization test.

Check original conversations/files, a new recording, to-do updates, AI settings,
Memories and saved chats. Reopen a saved chat after refresh and follow up.

## Restricted PostgreSQL runtime role

Run the following using an authorised database administrator on DEVELOPMENT first.
Do not run against production as a test. If the database account cannot create
roles, arrange role provisioning through the database administrator/provider.
Keep passwords and full database URLs out of chat, Git and screenshots.

Example in psql (replace the role name if already in use):

```sql
CREATE ROLE memory_runtime LOGIN NOSUPERUSER NOBYPASSRLS
  NOCREATEDB NOCREATEROLE NOINHERIT;
\password memory_runtime
GRANT USAGE ON SCHEMA public TO memory_runtime;
GRANT SELECT ON workspaces, workspace_memberships, themes TO memory_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  entries, jobs, processed_entries, knowledge, knowledge_changes, assets,
  search_records, memory_projects, memory_topics, memory_project_entries,
  memory_records, memory_proposals, memory_revisions, memory_chat_threads,
  memory_chat_turns, workspace_ai_settings TO memory_runtime;
```

Ensure the role can CONNECT to this database. Do not grant it schema ownership,
CREATE, ownership-role membership, migration-table writes or membership-table writes.
The application uses UUIDs, so these tables do not require sequence grants.

Configure Render:

1. Set MIGRATION_DATABASE_URL on the development WEB service only to its existing
   schema-owner URL. Alembic uses it; start.sh unsets it before launching HTTP.
2. Set DATABASE_URL on development WEB and WORKER to the same database using the
   memory_runtime username/password. Keep all other connection options unchanged.
3. Redeploy web and worker. Do not put MIGRATION_DATABASE_URL in their shared group.
4. Rerun the audit. Require runtime_isolation_ready=true before tester onboarding.

New tables in later migrations need explicit runtime grants and RLS policies.
Never copy development database or auth credentials into production.

## Tests and remaining gate

Validation on 6 October 2026: 92 tests passed, including the real-HTTP browser
journey; two PostgreSQL-only tests were skipped. Frontend production build passed.

Two-account API tests cover duplicate content/names, foreign IDs, file downloads,
chat history/send/stream attacks, settings separation, membership revocation,
normalisation/memory/embedding workers, semantic candidate filtering, bulk writes,
missing scope and embedded evidence references. Existing regressions are retained.

PostgreSQL could not start in this execution environment (OS user-management
permissions are unavailable). The RLS test is supplied but remains unexecuted here.
Use an EMPTY DISPOSABLE PostgreSQL database with role-provisioning credentials:

    TENANCY_RLS_TEST_DATABASE_URL=... python -m pytest tests/test_tenant_postgres.py -q

It refuses a nonempty database, migrates to head, grants a restricted NOLOGIN role,
checks forced RLS with raw reads/writes, absence of tenant context, pooled connection
reuse and lack of membership-write privileges. It removes its temporary role but
leaves the disposable data/schema for inspection. Use a fresh database for each run.
Never point this test URL to Render dev or production.

Production promotion and Phase 3 tester invitations remain gated on this rehearsal,
live dev checks and deployment role verification. Code completion does not imply
that production credentials or PostgreSQL RLS have been externally verified.

## Recovery

Do not roll back to pre-0010 writers or remove tenant ownership/RLS to restore service.
Disable tester access, retain the restricted role and fix forward with compatible
code. Restore a verified backup only through a deliberate recovery procedure.
Migration 0010 deliberately disallows automatic downgrade.
