# Jaeger WebUI manual click checklist

Companion to `scripts/verify-stack-smoke.py` (API-level smoke). Browser
button-level coverage is not fully automated here — use this list after the
smoke matrix is green.

**Chat face:** http://100.74.2.15:8790/ (or http://127.0.0.1:8790/)  
**Hermes runtime:** :8787 — not a chat bookmark.  
**Adapters:** Jaeger :8642 · Roundtable :8643 · OpenClaw :8644  

**Profiles that must stay available** (switch via titlebar profile chip / Agent profiles tab):

| Profile id | Display name |
|------------|--------------|
| `default`  | Hermes Agent |
| `jaeger`   | Jaeger |
| `openclaw` | OpenClaw |
| `roundtable` | Roundtable |

Repeat the sections below **once per profile**.

---

## Rail tabs (every profile)

- [ ] **Chat** — conversation list loads; pick/open a session
- [ ] **Tasks** — cron/job list loads; Refresh
- [ ] **Kanban** — board loads; Refresh (do not Run dispatcher unless intentional)
- [ ] **Skills** — skills list loads
- [ ] **Memory** — memory panel loads
- [ ] **Spaces** — workspaces list loads
- [ ] **Agent profiles** — profiles list includes Hermes Agent / Jaeger / OpenClaw / Roundtable
- [ ] **Todos** — current task list loads
- [ ] **Insights** — insights panel loads; Refresh
- [ ] **Logs** — logs load; Refresh (Copy all optional)
- [ ] **Settings** — settings sections open (providers, theme, etc.)

## Chat / composer controls (every profile)

- [ ] **New conversation** (titlebar + sidebar)
- [ ] **Profile switch** (titlebar profile chip / Agent profiles → Activate)
- [ ] **Workspace chip** — open dropdown; confirm space list
- [ ] **Model chip** — open dropdown; models load
- [ ] **Reasoning chip** — open dropdown
- [ ] **Toolsets chip** — open dropdown
- [ ] **Attach** — file picker opens (cancel without uploading)
- [ ] **Saved prompts** — popup opens
- [ ] **Dictate / Mic** — permission prompt or disabled state is sane
- [ ] **Voice mode** — toggles or shows capability state
- [ ] **YOLO pill** — toggles (leave OFF after check)
- [ ] **Send** — with a harmless ping (optional; uses model tokens)
- [ ] **Workspace panel** toggle / collapse
- [ ] **Scroll to bottom** / **Jump to session start** / **Outline** (with a long session)

## Session sidebar

- [ ] Session search / clear filter
- [ ] Open existing session
- [ ] Rename session (optional)
- [ ] Archive / delete (optional — prefer a throwaway “Verification — …” session)

## Tasks tab actions (careful)

- [ ] New job (open form, cancel)
- [ ] Refresh job list
- [ ] Run now / Pause / Resume / Edit / Duplicate / Delete — only on a disposable job

## Kanban tab actions (careful)

- [ ] New task (open form, cancel)
- [ ] New board (open form, cancel)
- [ ] View toggle
- [ ] Preview dispatcher (dry-run) — preferred over Run dispatcher
- [ ] Run dispatcher — only if intentionally testing

## Skills / Memory / Spaces / Profiles

- [ ] Skills: New skill (open form, cancel); toggle enable if safe
- [ ] Memory: open item; Edit/Cancel without saving unwanted changes
- [ ] Spaces: Add space (open form, cancel); Use this space on an existing space
- [ ] Profiles: Activate each of the four required profiles; do **not** Delete

## Gateway / health banners

- [ ] Agent health alert dismiss (if shown)
- [ ] Restart gateway button — **only** if intentionally testing restart
- [ ] Approval card Once / Session / Always / Deny / Skip-all — only with a live tool prompt
- [ ] Clarify submit — only with a live clarify prompt

## Reload / update surface

- [ ] Titlebar Reload
- [ ] Updates panel (check / apply) — prefer check-only; avoid force-update on shared hosts

---

## API coverage already exercised by smoke

`verify-stack-smoke.py` hits, per profile cookie:

- `/api/profile/switch`, `/api/profile/active`
- `/api/sessions`, `/api/models`, `/api/gateway/status`
- `/api/health/agent`, `/api/settings`, `/api/skills`, `/api/memory`
- `/api/workspaces`, `/api/crons`, `/api/insights`, `/api/auth/status`
- Adapter `/health` on :8642 / :8643 / :8644
- Chat face HTTP on :8790

Live LLM + tool path (creates sessions, spends tokens):

```bash
./scripts/verify-stack-smoke.py --start --live
# or directly:
.venv/bin/python scripts/verify-agent-webui.py --url http://127.0.0.1:8790/
.venv/bin/python scripts/verify-native-webui.py --url http://127.0.0.1:8790/ --profile jaeger
```
