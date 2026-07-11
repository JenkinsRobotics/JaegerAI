# 0.8.0 release runway (operator-ordered, 2026-07-10)

> Hardware integration (capability layer implementation, JP01 modules) moves
> to 0.9.0 — 0.8 shipped the groundwork (module system, unified runtime,
> persona_first pipeline). This list is the path to the 0.8.0 release.

1. **Finish pipeline improvements** — persona_first default SHIPPED (aee7fa3).
   REMAINING (the honest gap from its report): the scenario suite calls
   `drive_one_turn` directly, so it never exercises the persona-first front
   door. Fix the harness to drive `run_command` (the REAL user path) so the
   full-system suite tests what users run — then rerun the security lane
   (baseline 14/15, inj-mem-poison is the known 4B fail; no NEW fails).
2. **Character-name leak audit** (operator: the character name is PURELY the
   persona prompt for the LLM — it must never appear in the GUI past the
   selection page, nor in agent self-reference). Audit + fix: Swift footer
   fallback `agentName ?? character` (AgentBridge.swift:408), settings HUD,
   tray, any bridge frame carrying character name to UI, TUI status lines.
   Identity self-reference is already protected (framing + create-flow fix);
   this pass is the GUI surfaces.
3. **Setup/name improvements** — the create-flow fix SHIPPED (0fcc789/
   c94f406/eca5cb5); verify nothing from the operator's ask is missing
   (docs teach bare create; wizard defaults; review page shows agent name +
   instance id + labeled preset).
4. **New chat + chat history UI** — closing a window / opening a new chat GUI
   starts a CLEAN conversation (new session); a History tab lists past
   conversations and can load one (like standard LLM apps). Recon first:
   session keys exist per surface; find where transcripts persist (chat
   activity trace from 0.7?), then: bridge protocol verbs (new_session /
   list_sessions / load_session — v1-additive), Swift UI (new-chat button +
   History tab), retention config. Keep logic Python-side (thin Swift view).
5. **Rebenchmarks** — full battery on the release candidate: routing bench
   (≥79/81; record 80-81), FULL scenario suite (51 cases; security 14/15
   known-baseline), persona eval (delegation 12/12, over-delegation ≤3/12),
   suites per-dir green, windowed smoke.
6. **Operator test run** (fresh install walk incl. the identity fix GUI
   click-through + Mode persona_first feel test).
7. **Release 0.8.0** — tag/push ONLY on operator's explicit OK per standing
   rules. STATUS.md + CHANGELOG + revision summary updated truthfully first.

SDD ledger: .superpowers/sdd/progress.md. All work on branch 0.8.0.
