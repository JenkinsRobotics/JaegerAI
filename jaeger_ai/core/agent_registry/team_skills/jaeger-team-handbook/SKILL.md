---
name: jaeger-team-handbook
description: Shared rules for every Jaeger team agent - project root, team notes, evidence, and how results flow back to the lead.
metadata:
  role: shared
  version: "1"
---

# Team handbook (every agent)

- **Project root is the only place you write.** The task names it; your tools are
  already confined to it. Never write outside it, never `git push`, never touch
  `~/.jaeger`, disks, or system settings.
- **Hand context forward in your result.** The lead passes your findings to the next
  specialist in its task text, so put every decision others need in your final
  result. Keep private scratch in `agent_notes`.
- **Evidence over claims.** Every result lists what you actually ran or read:
  file paths, command + exit code, tool names. Say plainly what you did not verify.
- **Results return as a message.** Your final answer is posted into the chat that
  asked for it, attributed to you. Make it self-contained: summary, evidence,
  open issues, next step.
- **Stay in your lane.** If the task needs another role (design, build, review,
  research, reverse engineering), say so in the result instead of improvising it.
