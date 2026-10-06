# Phase 5: saved chat interface

## Rollout

Deploy the development web service from this commit. Startup must have applied Phase 4 migration `0008`. No additional migration, variable or worker change is required. `MEMORIES_ENABLED=true` enables Memories and Chats together. Production promotion remains separate.

## Experience

- Chats in navigation provides searchable/paged global history and new project/topic-scoped discussions.
- Topic Ask shows its saved threads and New chat. Project overview can start project-wide discussions. Ask across project explicitly creates a new, broader thread; it does not move the original thread or copy its messages.
- Recent chats in the desktop sidebar opens saved threads directly. It uses the same backend history and is hidden in collapsed/mobile navigation.
- The composer supports follow-ups, explicit memory-history inclusion, saved failed-turn retry and polling of pending responses. Model choices remain saved on each turn.
- Citation buttons open source excerpts in a dialog without navigating away or losing the draft. Saved responses display warnings if their evidence has changed.
- Expand chat widens the topic pane; Return to pane restores the map alongside it. Global Chats provides a wide reading layout. Mobile retains accessible bottom navigation and a sticky composer.
- Rename changes the thread title with optimistic version checking. History pages older messages rather than loading an unbounded transcript.

## Response transport and durability

`POST /api/memories/chats/{id}/turns/stream` adds an authenticated SSE transport for the existing turn submission. It emits a live progress event, keepalives, then the completed validated turn (or structured error event). Provider adapters still generate structured answers as a whole. **This is not token-by-token model output or simulated typing**: source/citation checks finish before any answer text is displayed.

Generation runs in its own database session. Navigating away or a dropped browser connection does not intentionally cancel it. Saved thread state remains authoritative after a timeout. The UI keeps an uncertain submission's UUID and can check saved state or retry the same submission; it does not silently invent a new UUID and duplicate the question. A failed/expired turn uses the backend retry endpoint.

Drafts and uncertain request identifiers survive navigation within the current app session in memory. They are not stored in localStorage or persisted through a page refresh/browser restart, and are cleared on sign out. Submitted questions and completed answers remain in the database. After a refresh during generation, reopen the saved chat to poll its state. If the submission never reached the server and the page was refreshed, its unsent draft is not recoverable.

## Test in development

1. Open Memories → a project → a topic → Ask → New chat. Ask a supported question, then a follow-up. Open Source 1 and close the evidence dialog.
2. Expand chat, then Return to pane. Check that the same thread stays open.
3. Start another chat under the same topic. Confirm it has no messages from the first discussion.
4. Type an unsent draft, navigate to Chats, and reopen that thread. Confirm the draft remains. Do not refresh for this check.
5. Resume the first thread from global Chats or Recent chats. Confirm its saved messages and original scope.
6. Select Ask across project. Confirm a new project-wide chat opens and the original topic thread remains in history.
7. Reload after a completed answer. Reopen the saved chat and check citations. Check renamed titles in history.
8. On a phone, check source dialogs, the composer above bottom navigation, and navigating between Chats and Memories. Physical keyboard/safe-area behaviour remains a real-device check.

Automated validation: 83 backend tests, including SSE success/conflict and all Phase 4 isolation/retry checks; 14 frontend unit tests including split UTF-8 streams, interrupted stream handling and conflict metadata; existing recording/settings/auth/MFA smoke tests; browser journeys for topic chat, follow-ups, citations, independent threads, in-session draft preservation, history reopening, failed-turn retry, pane expansion and mobile widths. Providers and auth are mocked in browser tests; live-provider answer quality and Render's stream behaviour require dev validation.
