# Companion UI redesign

## Shipped foundation

The existing Agents tabs remain unchanged. Chat retains its durable session and
mounted conversation while navigating. The outer shell uses a narrow icon rail beside a tab-specific context panel;
secondary work/research/machine/task destinations live under More tools. There is
no second bottom dock. Selecting a tab keeps its context panel open. The drawer closes via its close
control, Escape, or the backdrop.

- Imagine: existing Studio providers, generation, asset imports and board.
- Library: Media, Documents and Outputs reuse Studio, LibraryControls and
  TaskArtifacts. This is not yet a complete aggregation of chat attachments.
- Automations: the existing ScheduleControls owner, including operation recovery,
  editing, pause/resume, run history and cancellation confirmation.
- Feed: existing Notifications owner. Agent activity only, not fabricated news.

## Remaining product work

- Connect the existing durable GoalService to owner-scoped UI controls and life
  areas. Do not create another goals database.
- Connect proactive Ideas and curated feed sources, including source links,
  preference editing and scheduling. Activity notifications alone are not this.
- Aggregate shared chat attachments into Library without copying authoritative
  records or granting new file access.
- Finish the Work, Research and Machine screen redesigns, preserving operations.
- Integrate role-optimized team delegation through existing agent controls.

Image capabilities remain those of configured providers; the UI does not bypass
provider policy or silently select a paid provider.

## Avatar and mode-switch delivery (2026-11-07)

- The approved sculpted Jaeger character now has six silent, pre-rendered H.264
  loops and a 512px portrait in public/assets/avatar/jaeger. These are offline
  2.5D motion composites (including smile motion), not newly generated 3D rigs.
- Only the conversation header animates and shows live activity text. Lists,
  cards and the separate avatar panel stay static. Reduced motion and failed
  playback use the portrait. Existing custom portraits remain respected.
- Chat lifecycle and structured tool/handoff events choose the activity state;
  historical completed turns do not trigger celebrations.
- The sidebar title has a Jaeger/Team picker. Team opens the existing Agents
  workspace; Jaeger returns to the mounted conversation. This is the entry point,
  not yet a full digital-office visualization.
- Avatar restyling/new-character generation with bundle preview and confirmation
  remains pending. The shipped bundle is the approved default, not that editor.
