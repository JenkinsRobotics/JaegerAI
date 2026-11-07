# Rev 3 — Milestone 1 navigation migration

The Desktop spec and prompt were read in full. Current UI was checkpointed at
f98bf80748c53454f5406a18ab50bd4396108708 before edits. This is IA only;
Chat redesign/full-turn proof, Agents polish, unified Work projection, and Settings
health redesign remain their later milestones. No backend records are changed.

## Source correction authorized by Matthew: “just finish it” (2026-11-06 PST)

The spec's assertion that the four Work panels are one queue is not true of the
current implementation. `unified/backlog.ts` uses independent `/v1/backlog` IDs,
statuses and assignment actions. `PipelinePage.tsx` combines gateway tasks with
pipeline metadata and WebUI-only jobs. `TasksWorkspace.tsx` uses gateway task
states. Preserve each identity, provenance, action and evidence. Milestone 4 may
project these into one UI board, but must not merge, migrate or delete backend
records or infer verified completion from pipeline stage alone. During IA-only
Milestone 1 the four existing Work panels remain reachable inside Work.

## Exhaustive old → new destination mapping

| Old destination | New destination |
| --- | --- |
| Home / Overview | Work landing content; Chat's existing status/approval chrome retained |
| Home / My widgets | Settings gear / My widgets |
| Chat | Chat, default `/`, kept mounted across navigation |
| Agents / roster | Agents / roster |
| Agents / Characters | Agents / Characters |
| Agents / Hermes, OpenClaw | Settings gear / Integrations / Hermes, OpenClaw sections |
| Work / Pipeline, Backlog, Tasks, Production | Work, existing panels/actions retained pending Milestone 4 projection |
| Work / Calendar | Work / Calendar |
| Work / Workspace | Research / Workspace |
| Work / Checkpoints | Settings gear / Checkpoints |
| Research / runs | Research / runs |
| Research / YouTube | Work / YouTube |
| Research / Documents | Research / Documents |
| Research / Memory & Skills | Agents / Memory & Skills |
| Research / SharePoint | Settings gear / Integrations / SharePoint section |
| Studio | Studio, unchanged |
| Models / Library, Compare, Usage | Settings gear / Models, one page with sections; existing provider controls retained |
| Machine | Machine, unchanged |
| Settings | Settings gear, existing panels retained |

Old route prefixes, deep-link tails and query strings redirect to the new homes.
Saved 9-tab and older layouts migrate to six ordered tabs plus the footer gear.
No obsolete UI files are deleted and no backend, auth, ports or services change.
