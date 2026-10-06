# Memories interaction prototype

Open `memories-cloud.html` in a browser. It is a standalone, offline design prototype, not a production route. All content, quotes, and answers are illustrative sample data. There are no API requests or AI calls.

Try PNB Edge → Demo → View sample source → Ask about Demo → What is still open. Use the scope selector, theme filter, project/topic search, Map/List switch, and breadcrumb navigation. On phone widths, details replace the map until Back to map is selected. Asking within another scope is explicit; changing the map does not silently retarget existing answers.

This first prototype explores layout and transition direction. It does not implement memory ingestion, reconciliation, real citations, arbitrary-question answering, or large-collection layout. Physical-device motion/performance and larger datasets remain follow-up validation before app integration.

Browser checks: from `frontend`, install the existing dependencies and Playwright Chromium, then run `node tests/memories-prototype.cjs`. Checks cover project/topic navigation, evidence, contextual sample answers, search, list view, mobile widths, and reduced motion.
