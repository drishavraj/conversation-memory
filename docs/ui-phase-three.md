# Phase 3: spatial memory exploration

Deploy the development web service from this commit. No new environment variables, database migration or worker update is required.

## Included

- Organic, bounded clouds with deterministic collision-free positions and consistent Office/Personal/Side Projects colours and labels.
- Project-to-topic transition, breadcrumbs, search, list view, zoom, Fit all, drag and keyboard panning. Keyboard focus brings an off-screen node into view. Reduced-motion preferences disable transitions.
- Camera restoration when returning to the project map within the Memories screen. Cloud coordinates survive local filtering and pane resizing. Full reloads reconstruct deterministic positions from the same ordered data. A changed collection can require a new layout.
- Projects are fetched in pages of 30; next/previous navigation remains available for larger collections. Each project's existing maximum of 100 topics is supported. New large maps start at a readable zoom centred on the first node; Fit all provides an overview, and List view provides full readable labels.
- Desktop topic details appear alongside the map in a 380px pane with Overview, Ask and Sources. At widths of 800px and below, details replace the map with Back to map. Long desktop details scroll while pane controls remain available.
- Linking, retrying and unlinking conversations live under Sources. Review controls appear when pending suggestions exist. Empty projects offer linking as the main next step. Project overview supports memories not assigned to a topic.

Ask still uses the existing single-question endpoint. Persistent multi-turn chats, saved history and the expanded chat workspace belong to subsequent phases. No chat history or auto-classification is implied by this release.

## Test on dev

1. Open Memories with several projects. Check that clouds are scattered, readable and consistently coloured.
2. Zoom, drag empty space, use Fit all and switch to List view. Check a long project name in List view.
3. Enter a project and select a topic. Try Overview, Sources and Ask. Confirm the visible scope before asking.
4. Under Sources, link a conversation to the topic, then review and accept its suggestions from Overview. Verify existing review/history behaviour still works.
5. Close the pane, use breadcrumbs, and confirm the map's location is retained. Search and clear the query.
6. On a phone, select a topic and return with Back to map; verify bottom navigation remains usable. Try actual touch dragging and page scrolling outside the map.
7. Check an empty project, light/dark appearance, keyboard Tab navigation and reduced-motion mode.

Automated checks cover non-overlapping deterministic layouts with 1, 4, 12, 30 and 100 nodes; browser checks cover real API contracts (mocked providers), topic linking/review/Ask, desktop/mobile layout, zoom/list controls and 1/4/12/30 project fixtures. Live AI quality and physical-device touch/keyboard behaviour require dev validation.
