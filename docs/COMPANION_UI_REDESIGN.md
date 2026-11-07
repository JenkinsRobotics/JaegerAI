# Companion UI redesign

## Shipped foundation

The existing Agents tabs remain unchanged. Chat retains its durable session and
mounted conversation while navigating. The outer shell uses one labeled sidebar;
secondary work/research/machine/task destinations live under More tools. There is
no second bottom dock. On small screens the drawer closes after choosing a
page, via its close control, Escape, or the backdrop.

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
