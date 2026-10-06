# Phase 2: shared design system and application shell

This release adds locally bundled Inter fonts (400/500/600), neutral light/dark tokens, consistent controls and compact dialogs, a compact page header, a collapsible desktop sidebar, and an account menu. User identity uses authenticated Supabase name metadata when present, falling back to the email prefix; initials are generated from that name. The complete email remains available in the account menu. There is no placeholder identity in the application.

On desktop the account sits at the bottom of the sidebar. On mobile its initials button sits at the top right while primary navigation stays at the bottom. Settings, system/light/dark appearance and sign out are accessible from the menu. Appearance and sidebar preferences persist locally. Signing out uses the existing authentication flow and recording-leave guard.

The development banner becomes a compact environment badge. The page title and theme filter share a row. Existing authenticated workflows and API contracts remain unchanged. A separate design-system stylesheet overrides legacy feature presentation; generated font files and the Inter OFL license are copied into the static build from the locked npm dependency. No external font service is called at runtime.

## Deploy and check

Deploy the development web service from this commit. No database migration, new environment variable, or worker update is required for these frontend-only changes. If automatic deploys are enabled, wait for the web service to become live. Reload the app after deployment.

1. Check the compact header and environment badge in Memories, To-dos and Conversations.
2. Open the account menu. Check your name/email, switch appearance, open Settings, and sign out/re-authenticate with MFA.
3. Collapse/expand the desktop sidebar. Reload to check preference persistence.
4. On a phone, open the account menu, switch screens, and confirm menus stay within the screen.
5. Record, stop, and save a short test. Save remains above the bottom navigation. Verify upload progress and processing stages.
6. Complete a to-do, open an entry, inspect sources, and open project/topic dialogs.

Automated checks: existing browser smoke suite (including MFA and recording), Memories browser suite with account identity/menu/collapse/font/header/mobile checks, and processing-progress unit tests. No backend changes are included. Physical phone keyboard/safe-area behaviour remains a real-device rollout check.

## Later phases

The organic spatial cloud layout, topic-pane redesign, persistent chat backend, chat history and streaming interface are subsequent phases. Phase 2 does not introduce placeholder Chats navigation or replace the existing single-question Ask endpoint. The cloud grid remains until Phase 3.
