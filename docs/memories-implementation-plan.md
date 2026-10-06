# Memories: implementation plan

Status: proposed scope, 6 October 2026. This document does not implement the feature.

## Product outcome

Make Memories a distinct destination: an animated, explorable map of projects and topics that leads to current, evidence-backed knowledge. The visual experience is a product differentiator; usefulness is measured by finding current context, changes, and open commitments quickly.

Preserve Record and To-dos as primary activities. Add Memories alongside Conversations. Themes remain Personal, Office, and Side Projects; projects such as PNB Edge live within a theme. Topics such as MVP, Demo, and Commercials live within projects, with many-to-many links from memories to topics.

## Phase 1 — Interaction prototype and visual direction

Build a separate interactive prototype using clearly labelled sample data, before changing production navigation or adding database tables.

- Home: labelled project clouds, theme filter, search, and Map/List switch.
- Project: select a cloud to zoom smoothly into related topics, retaining a breadcrumb and Back control.
- Topic: reveal a readable detail panel with current facts, decisions, open actions, questions, and source links. Stop at this depth rather than requiring endless zooming.
- Desktop: contextual Ask in a right rail; use tabs within the rail to switch between topic details and Ask rather than squeezing two panels beside the map.
- Mobile: topic detail and Ask use a bottom sheet or full-screen view; persistent scope selector and Back control.
- Scope changes must be explicit. Do not silently retarget an existing Ask conversation when a user selects a different cloud.

Visual direction: soft, organic clusters with clear typography, restrained gradients, subtle depth, and crisp selected states. Avoid cartoon cloud clip art and unreadable word-cloud layouts. Use deterministic positions; new content must not reshuffle the whole map.

Motion specification, to tune in prototype:

- Project selection: 300–450 ms camera transition, with children emerging from the selected parent and a clear breadcrumb update.
- Back: reverse the spatial transition and restore previous position and selection.
- Hover/focus: 120–180 ms emphasis, with equivalent touch and keyboard affordances.
- New knowledge: one brief highlight on the affected cloud; no continuous attention-seeking pulses.
- Ambient motion: optional, very low amplitude, paused during interaction and when offscreen; disable entirely for reduced motion and on constrained devices if necessary.
- Reduced motion: instantaneous navigation or a short fade; all functionality remains available.
- No animation may delay an action, move a target under the pointer, or cause layout reflow on the rest of the page.

Acceptance: prototype all navigation on desktop and phone widths; keyboard access and readable labels at 320 px; map remains understandable with 1, 10, and 50 projects. Initially show a bounded set of pinned/recent projects and offer search/View all. Test before committing to a rendering library. Prefer DOM/SVG for the initial bounded map; introduce Canvas/WebGL only if measured performance requires it. No framework rewrite is a prerequisite.

## Phase 2 — Project and memory foundation

Add additive migrations for projects, project aliases, topics, entry-project links, memory-topic links, canonical memory records, supporting evidence, memory revisions, relationship records, and proposed changes.

Canonical memory fields should include owner scope, theme/project, subject, predicate, value, certainty, status, event/effective time, recorded time, revision, and source references. Distinguish a source statement from accepted current knowledge. Preserve originals and previous revisions. Allow an entry to cover more than one project.

APIs: project/topic management; link/unlink conversations; paginated project overview; bounded map neighbourhood; memory history/evidence; and review proposals. Enforce the existing owner authentication and MFA checks on every endpoint. Scope all queries by owner and theme/project, not just the frontend filter.

First release uses manual project assignment plus optional suggestions. Existing entries stay valid and unassigned until linked; do not silently organise or rewrite the entire archive. Backfill must be previewable, resumable, and idempotent.

Acceptance: linking the same source twice produces no duplicate evidence; one memory can appear under two topics without duplicate storage; deleted/unlinked evidence invalidates affected derived views appropriately; existing upload and retrieval flows still work.

## Phase 3 — Evidence-backed current knowledge

Extend the durable worker after extraction with independent, checkpointed tasks: project/topic linking and memory reconciliation. Add their provider/model settings through the existing task-specific configuration and UI; persist choices with queued jobs.

Retrieve bounded candidate matches before asking the model to propose new, supporting, changed, conflicting, or possible-completion relationships. Validate model output against schemas and source evidence. Use canonical project aliases and entity identifiers where confirmed; do not rely only on text similarity.

Initially automate clear additions/supporting evidence; require review for replacements, project merges, conflicts, and suggested action completion. Newer upload time alone never makes a fact authoritative. Respect event time, certainty, explicit supersession, and speaker attribution. An unconfirmed proposal must not overwrite a confirmed decision.

Review UI: existing fact, proposed update, exact supporting quote/date, Accept, Keep existing, and Edit. Keep rejected proposals auditable and support correction/undo through revisions. Conflicting claims remain visible until resolved. A revision race should request a refresh, not overwrite another update.

Acceptance fixtures: Friday tentative → Friday confirmed → Monday explicit change; older meeting uploaded later; two speakers disagreeing; repeated identical upload; ambiguous project alias; failed provider/retry; a later statement suggesting a to-do was completed. Test that completed checkpoints are reused and rejected proposals do not alter accepted memory.

## Phase 4 — Connect the cloud UI to real knowledge

Replace prototype data with scoped project/topic endpoints. Persist stable positions or deterministic layout seeds. Show explicit counts and attention badges; do not use cloud size as an unexplained importance score. Draw only meaningful relationships with a visible explanation/evidence on selection. Avoid showing every possible connection at once.

Topic details prioritise Current position, Decisions, Open actions, Open questions, and What changed. Bound text previews and offer View full content. Show sources on every generated factual claim. Keep an equivalent searchable List view for accessibility and large collections.

Retain source conversations as the detailed record. Progressive results, if added, must use actual persisted outputs; currently some results are only published to the knowledge view after processing completes.

## Phase 5 — Contextual Ask

Add explicit all-memory/project/topic scope to retrieval and answers. Retrieve accepted current memories plus necessary historical context and original source excerpts. Questions about changes must retrieve revisions, not only current state. Cite sources, disclose unresolved conflicts, and return no-evidence when appropriate.

Preserve the visible scope with each question and answer. A topic click may offer to start a newly scoped question; it must not change the meaning of existing messages. Ensure broad-scope retrieval cannot leak data across owner or theme boundaries.

Acceptance questions: Where do we stand? What changed since the previous meeting? What blocks the demo? What did I commit to? Test conflicting, absent, historical, and cross-project evidence.

## Phase 6 — Release quality and rollout

- Develop first, behind a Memories feature flag; existing Record, To-dos, and Conversations remain usable if disabled.
- Run additive migrations before enabling new worker tasks; deploy compatible API and worker builds, then enable the UI. Make retry/backfill safe across restarts.
- Evaluate animation on a physical iPhone, reduced-motion settings, keyboard navigation, long labels, large datasets, empty states, and provider failures. Aim for smooth 60 fps transitions on target devices; measure rather than assume.
- Test map/list parity, citation fidelity, proposal review, stale revisions, deletion, and isolation. Include realistic data volumes and a small labelled evaluation set for reconciliation quality.
- Track task success, time to find an answer, incorrect merge/update rates, review rejection rates, latency, and provider cost per conversation. Avoid logging raw conversation content or secrets as telemetry.
- Promote tested work through a PR into main. Roll back the flag/code without dropping memory tables or source data.

## Scope boundaries

No native app, autonomous reminders, team collaboration, billing, or multi-tenant commercial launch in this milestone. A saleable hosted product would separately require account isolation beyond the current owner-only setup, retention/deletion controls, operating-cost controls, and commercial onboarding. Keep this repository open source, document provider setup, and review licences of any new visual dependencies.

## Build order and approval gates

1. Approve the animated prototype and navigation using PNB Edge sample content.
2. Build project linking and source-backed memory storage.
3. Add reconciliation and review, with evaluation fixtures.
4. Connect the approved cloud UI and contextual Ask.
5. Pilot with one real project; validate usefulness and motion on phone; then promote to production.

The visual prototype is the next implementation step. The plan does not authorise fabricated relationships or automatic replacement of existing production knowledge.
