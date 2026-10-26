# JaegerAI vs Hermes Agent vs OpenClaw — Stack Comparison

**Assessment Date:** 2026-10-25
**Purpose:** Determine whether JaegerAI can fully replace Hermes Agent and OpenClaw.

---

## Executive Summary

| | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Stars** | Private | 257k ⭐ | 393k ⭐ |
| **Language** | Python (71%) + TypeScript | Python (71%) + TypeScript (25%) | TypeScript (90%) |
| **Built by** | Jenkins Robotics | Nous Research | OpenClaw Foundation (Peter Steinberger) |
| **License** | Apache-2.0 | MIT | MIT |
| **Philosophy** | Proactive world-model companion with robotics integration | Self-improving agent with closed learning loop | Personal AI assistant on your devices, every chat app |
| **Primary Use Case** | Standalone intelligence stack + robotics + YouTube/business ops | Autonomous agent that learns and improves | Gateway connecting chat apps to coding agents |

**Verdict:** JaegerAI covers **~65-70%** of Hermes+OpenClaw combined use cases today. It excels in robotics integration, proactive world-model intelligence, on-device trust, and multi-surface clients (Mac/Web/TUI/IDE). It lags in messaging platform breadth (4 vs 20-30+), skills ecosystem maturity (107 vs 171+), and cross-platform deployment (macOS-first vs universal).

---

## 1. Feature Matrix

### 1.1 CLI Commands

| Category | JaegerAI (`jaeger`) | Hermes Agent (`hermes`) | OpenClaw (`openclaw`) |
|---|---|---|---|
| **Chat/Run** | `jaeger`, `jaeger "prompt"`, `jaeger --voice`, `jaeger --stream` | `hermes`, `hermes chat`, `hermes -z "prompt"` | `openclaw tui`, `openclaw chat`, `openclaw agent` |
| **Agent Management** | `jaeger agent create/list/use/inspect/delete/clear` | `hermes profile create/list/use/delete/show/export/import` | `openclaw agents list/add/delete/bindings` |
| **Setup/Onboarding** | `jaeger setup`, `jaeger onboard`, `jaeger agent create --gui` | `hermes setup`, `hermes setup model/gateway/tools` | `openclaw setup`, `openclaw onboard`, `openclaw configure` |
| **Model Selection** | `jaeger backends`, `jaeger runtime …` | `hermes model`, `hermes fallback`, `hermes moa` | `openclaw models list/set/aliases/fallbacks` |
| **Gateway** | `jaeger gateway daemon`, `jaeger gateway {install,start,stop,status}` | `hermes gateway {run,start,stop,restart,status,setup,install}` | `openclaw gateway {start,stop,restart,status,install,call}` |
| **Channels** | `jaeger channel …` | `hermes gateway setup` (interactive) | `openclaw channels {list,add,remove,login,logout,status}` |
| **Skills** | `jaeger skills …`, `jaeger skill …` | `hermes skills {browse,search,install,list,check,update,audit,uninstall,publish,snapshot,tap,config}` | `openclaw skills {search,install,update,verify,list,info,check,workshop}` |
| **Memory** | `jaeger memory …` | `hermes memory {setup,status,off}` + `hermes honcho …` | `openclaw memory {status,index,search}` |
| **Cron/Automation** | Via agent tools (`tools/scheduling.py`) | `hermes cron {list,create,edit,pause,resume,run,remove,status}` | `openclaw cron {status,list,add,edit,rm,enable,disable,run,runs}` |
| **Sessions** | `jaeger sessions [list]` | `hermes sessions {list,browse,export,delete,prune,archive,stats,rename}` | `openclaw sessions cleanup`, `openclaw transcripts {list,show,path}` |
| **Status/Health** | `jaeger status`, `jaeger doctor` | `hermes status`, `hermes doctor`, `hermes dump` | `openclaw status`, `openclaw health`, `openclaw doctor`, `openclaw triage` |
| **Configuration** | `jaeger config get/set`, `jaeger settings …` | `hermes config {show,edit,get,set,unset,path,check,migrate}` | `openclaw config {get,set,patch,unset,file,schema,validate}` |
| **Backup/Restore** | `jaeger backup`, `jaeger restore`, `jaeger migrate` | `hermes backup`, `hermes import`, `hermes profile export/import` | `openclaw backup {create,verify,restore,sqlite,git}`, `openclaw reset` |
| **Update** | `jaeger update`, `jaeger reinstall`, `jaeger uninstall` | `hermes update`, `hermes uninstall` | `openclaw update {wizard,status,repair}` |
| **Logs** | Via `jaeger status` | `hermes logs {agent,gateway,gui,desktop,errors} -f -n` | `openclaw logs`, `openclaw system event` |
| **Plugins** | `jaeger_ai/plugins/` (registry) | `hermes plugins {install,search,update,remove,enable,disable,list,doctor,pack}` | `openclaw plugins {list,search,inspect,install,uninstall,update,enable,disable,doctor,build}` |
| **Messaging Tools** | Discord/Telegram/iMessage plugins | `hermes send --to <platform>`, `hermes peer`, `hermes pairing` | `openclaw message {send,broadcast,react,read,edit,delete,pin,thread,role,channel,member,voice,event,timeout,kick,ban}` |
| **MCP** | `jaeger mcp`, `jaeger mcp --http` | `hermes mcp {catalog,install,add,remove,list,test,configure,login}` | `openclaw mcp {serve,list,show,set,unset}` |
| **Multi-Agent** | `jaeger delegate list/run/moa`, Roundtable, Dispatcher/Kanban | `hermes kanban`, Bot Mode, subagents, `hermes peer` | `openclaw agents`, `openclaw worktrees`, `openclaw worker`, `openclaw tasks` |
| **Voice** | `jaeger --voice`, `jaeger voice` | `/voice` slash command, voice mode | `openclaw voicecall` (plugin), node voice |
| **Browser** | Agent tools (`tools/browser.py`) | Browser tools + Nous Portal Tool Gateway | `openclaw browser {status,start,stop,tabs,open,click,type,screenshot,navigate,…}` |
| **Webhooks** | `jaeger_ai/features/webhooks/` | `hermes webhook {subscribe,list,remove,test}` | `openclaw webhooks`, `openclaw hooks` |
| **Security** | Approval gates, TCC permissions, `core/safety/` | `hermes security audit`, `hermes approvals`, DM pairing, container isolation | `openclaw security audit`, `openclaw approvals`, `openclaw sandbox`, DM pairing |
| **Completion** | Not explicit | `hermes completion {bash,zsh,fish}` | `openclaw completion` |
| **Debug** | `jaeger dev`, `jaeger dev --health` | `hermes debug share`, `hermes prompt-size` | `openclaw debug` (via `--log-level`), `openclaw dns` |
| **Total CLI Commands** | **~40+** | **~55+** | **~80+** |

**JaegerAI CLI Gaps:** Missing dedicated `cron`, `logs`, `pairing`, `send`, `browser`, `completion`, `webhook` CLI verbs (some exist as agent tools or feature modules). Missing `doctor --fix` auto-repair. Missing shell completion scripts.

---

### 1.2 Messaging Platforms

| Platform | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Telegram** | ✅ Live (`jaeger_ai/plugins/telegram`) | ✅ | ✅ Bundled |
| **Discord** | ✅ Live (`jaeger_ai/plugins/discord`) | ✅ | ✅ Official plugin |
| **Slack** | ⚠️ Thin (`features/channels/platforms/slack.py`, Socket Mode) | ✅ | ✅ Official plugin |
| **iMessage** | ✅ Live (`jaeger_ai/plugins/imessage`) | ✅ (BlueBubbles/Photon) | ✅ Official plugin (imsg) |
| **WhatsApp** | ❌ Planned (donor: openclaw/extensions/whatsapp) | ✅ (Baileys + Cloud API) | ✅ Official plugin |
| **Signal** | ❌ Planned (donor: openclaw/extensions/signal) | ✅ | ✅ Official plugin (signal-cli) |
| **Matrix** | ❌ Planned (donor: openclaw/extensions/matrix) | ✅ | ✅ Official plugin |
| **Mattermost** | ❌ | ✅ | ✅ Official plugin |
| **Microsoft Teams** | ❌ | ✅ | ✅ Official plugin |
| **Google Chat** | ❌ | ✅ | ✅ Official plugin |
| **Email** | ✅ Agent tools (`tools/email.py`) | ✅ | ❌ (via webhooks) |
| **SMS** | ❌ | ✅ (Twilio) | ✅ Official plugin (Twilio) |
| **LINE** | ❌ | ✅ | ✅ Official plugin |
| **WeChat/WeCom** | ❌ | ✅ (Weixin, WeCom) | ✅ External plugins |
| **DingTalk** | ❌ | ✅ | ❌ |
| **Feishu/Lark** | ❌ | ✅ | ✅ Official plugin |
| **QQ** | ❌ | ✅ | ✅ Official plugin |
| **Yuanbao** | ❌ | ✅ | ✅ External plugin |
| **BlueBubbles** | ❌ | ✅ | ❌ (uses imsg) |
| **Home Assistant** | ✅ Plugin (`jaeger_ai/plugins/homeassistant`) | ✅ Plugin | ❌ |
| **WebChat** | ✅ (WebUI :8790) | ✅ (Webapp) | ✅ Included in core |
| **Webhooks** | ✅ (`features/webhooks/`) | ✅ | ✅ |
| **A2A** | ✅ (`jaeger a2a`, :8796) | ✅ | ✅ Bundled plugin |
| **IRC** | ❌ | ✅ | ✅ Official plugin |
| **Nostr** | ❌ | ❌ | ✅ Official plugin |
| **Twitch** | ❌ | ❌ | ✅ Official plugin |
| **X/Twitter** | ❌ | ❌ | ✅ Bundled plugin |
| **Zalo** | ❌ | ❌ | ✅ Official + external plugins |
| **Nextcloud Talk** | ❌ | ❌ | ✅ Official plugin |
| **Synology Chat** | ❌ | ❌ | ✅ Official plugin |
| **Tlon** | ❌ | ❌ | ✅ Official plugin |
| **Total Platforms** | **4 live + 3 planned = 7** | **20+** | **30+** |

**JaegerAI Messaging Gaps:** Missing WhatsApp, Signal, Matrix, Mattermost, MS Teams, Google Chat, SMS, LINE, WeChat/WeCom, DingTalk, Feishu, QQ, Yuanbao, IRC, Nostr, Twitch, X/Twitter, Zalo, Nextcloud Talk, Synology Chat, Tlon. The channel catalog (`features/channels/catalog.py`) already lists WhatsApp, Signal, and Matrix as "planned" with OpenClaw donor sources.

---

### 1.3 User Interfaces

| Interface | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **CLI (REPL)** | ✅ `jaeger` (basic) | ✅ Classic CLI (prompt_toolkit) | ❌ (TUI only) |
| **TUI** | ✅ `jaeger_ai/interfaces/tui/` (prompt_toolkit, hermes-inspired) | ✅ Full TUI (multiline, slash autocomplete, streaming) | ✅ `openclaw tui` |
| **Web Dashboard** | ✅ Jaeger WebUI (:8790, React/Vite) + `features/webui` backend/proxy | ✅ Web Dashboard (:9119, FastAPI) + Webapp | ✅ Control UI (:18789, SolidJS) |
| **Desktop App** | ✅ macOS AppKit+WKWebView (`interfaces/macos-shell`) | ✅ Hermes Desktop (Electron, cross-platform) | ✅ macOS, iOS, Android, Windows apps |
| **Mobile Apps** | ❌ | ✅ iOS/Android (Hermes Mobile) | ✅ iOS + Android nodes (camera, screen, voice) |
| **IDE Extension** | ✅ VS Code extension (`interfaces/ide/`) | ✅ ACP server (`hermes acp`) | ✅ ACP support (`openclaw acp`) |
| **Avatar** | ✅ (`jaeger avatar …`, `interfaces/avatar/`) | ✅ Pets (petdex) | ✅ Canvas |
| **Bridge/SDK** | ✅ NDJSON over AF_UNIX (`interfaces/bridge.py`) | ✅ API server (`hermes serve`) | ✅ Gateway WebSocket + nodes |

---

### 1.4 Memory Systems

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Storage** | SQLite (`state.db`): facts, episodic, schedules, embeddings | SQLite + FTS5 (`state.db`), MEMORY.md, USER.md | SQLite (`openclaw.sqlite`), MEMORY.md, USER.md, daily notes |
| **Semantic Search** | ✅ `sqlite_search.py` + embeddings | ✅ FTS5 + LLM summarization | ✅ `memory_search` (hybrid: vector + keyword) |
| **Cross-session Recall** | ✅ Episodic memory | ✅ FTS5 cross-session recall | ✅ memory-core, dreaming |
| **External Providers** | ✅ Honcho (`features/shared_memory/`) | ✅ Honcho, Hindsight, Supermemory, Mem0, OpenViking, Holographic, Retaindb, Byterover | ✅ Honcho, LanceDB, memory-wiki |
| **Memory Files** | ❌ (SQLite-first) | ✅ MEMORY.md, USER.md, daily notes | ✅ MEMORY.md, USER.md, `memory/YYYY-MM-DD.md` |
| **Dreaming/Consolidation** | ❌ | ❌ | ✅ Background dreaming sweep, grounded backfill |
| **Knowledge Wiki** | ✅ (`features/knowledge_library/`) | ❌ | ✅ memory-wiki plugin |
| **Skill Tree/XP** | ✅ (`features/skill_tree/`) | ❌ | ✅ Skill Workshop |
| **Cost Tracking** | ✅ (`features/cost_tracking/`) | ✅ `/insights`, `/usage` | ✅ `openclaw status --usage` |
| **Memory Tools** | `memory.py`, `insights.py`, `persona.py` | `memory_search`, `memory_get`, `memory` tools | `memory_search`, `memory_get`, `intent` |
| **Profiles/Multi-tenancy** | ✅ Per-instance (`~/.jaeger/<name>/`) | ✅ Per-profile (`~/.hermes/profiles/<name>/`) | ✅ Per-agent workspaces |

---

### 1.5 Automation & Scheduling

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Cron Jobs** | ✅ Agent tools (`tools/scheduling.py`, `background/cron.py`, `cron_runner.py`) | ✅ `hermes cron` CLI + gateway ticker | ✅ `openclaw cron` CLI + Gateway scheduler |
| **Natural Language Scheduling** | ✅ ("remind me every morning") | ✅ | ✅ |
| **Delivery to Platforms** | ✅ Via channels | ✅ Any platform | ✅ Any channel |
| **Webhooks** | ✅ (`features/webhooks/`) | ✅ `hermes webhook subscribe` | ✅ `openclaw webhooks` |
| **Hooks** | ❌ | ✅ `hermes hooks` (shell-script hooks) | ✅ `openclaw hooks` |
| **Heartbeat** | ✅ (Entity sensors/salience) | ✅ | ✅ `openclaw system heartbeat` |
| **Missions/Goals** | ✅ (`features/missions/`) | ✅ Kanban tasks | ✅ `openclaw tasks` |
| **Workflows** | ✅ (`features/workflows/` — document-bound) | ❌ | ✅ (via cron + hooks) |

---

### 1.6 Skills System

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Skill Count** | **107** (jaeger-agent) + categories | **171** (core + optional) | Bundled + ClawHub community |
| **Format** | `SKILL.md` (agentskills.io compatible) | `SKILL.md` (agentskills.io compatible) | `SKILL.md` (agentskills.io spec) |
| **Registry/Hub** | ✅ `skill_market.py`, `skill_registry/` | ✅ Skills Hub (agentskills.io), `hermes skills browse/search` | ✅ ClawHub (clawhub.ai) |
| **Auto-creation** | ✅ `skill_improvement/`, reflection | ✅ Autonomous skill creation after complex tasks | ✅ Skill Workshop (agent learns skills) |
| **Self-improvement** | ✅ `skill_review.py`, curator-style sweep | ✅ Curator (`hermes curator`), skill self-improvement | ✅ Skill Workshop with undo |
| **Bundles** | ❌ | ✅ `hermes bundles` | ❌ |
| **Gating/Requirements** | ✅ `metadata` frontmatter | ✅ Platform/tool gating | ✅ `metadata.openclaw` (bins, env, config, os, install) |
| **Allowlists** | ✅ Toolset scoping | ✅ Per-platform tool config | ✅ Agent skill allowlists |
| **Catalog** | ✅ `skills/catalog.yaml` (core/plugin/explicit/optional) | ✅ 88+ optional skills | ✅ Bundled + ClawHub |
| **CLI Management** | `jaeger skills …` | `hermes skills {browse,search,install,inspect,list,check,update,audit,uninstall,reset,opt-out,opt-in,publish,snapshot,tap,config}` | `openclaw skills {search,install,update,verify,list,info,check,workshop}` |

---

### 1.7 Multi-Agent Support

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Multi-Agent Debate** | ✅ Roundtable (`features/roundtable/`) | ❌ | ❌ |
| **Task Dispatcher** | ✅ Dispatcher + Kanban (`features/dispatcher/`) | ✅ Kanban (`hermes kanban`) | ✅ `openclaw workboard`, `openclaw tasks` |
| **Subagent Delegation** | ✅ `call_agent.py`, `delegate` verb | ✅ Subagents, Bot Mode | ✅ `openclaw agents`, per-agent sessions |
| **Delegate to External** | ✅ `jaeger delegate list/run/moa` (claude, codex, hermes, openclaw, gemini) | ✅ `delegate_task`, `hermes peer` | ✅ `openclaw agent` (any harness) |
| **Mixture of Agents** | ✅ `jaeger delegate moa` | ✅ `hermes moa` | ❌ |
| **Worktrees** | ✅ `subagent_worktree.py` | ✅ `--worktree` flag | ✅ `openclaw worktrees` |
| **Cross-machine** | ✅ A2A (:8796), Agentgateway | ✅ `hermes peer` (bot-to-bot DMs) | ✅ Nodes (iOS/Android as remote workers) |

---

### 1.8 Model Providers

| Provider | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **OpenAI** | ✅ | ✅ | ✅ |
| **Anthropic** | ✅ | ✅ | ✅ |
| **Google Gemini** | ✅ | ✅ | ✅ |
| **OpenRouter** | ✅ (via compatible endpoint) | ✅ Native | ✅ |
| **Nous Portal** | ❌ | ✅ Native | ❌ |
| **Ollama (local)** | ✅ | ✅ | ✅ |
| **Ollama Cloud** | ✅ | ❌ | ✅ |
| **LM Studio** | ✅ | ✅ | ✅ |
| **llama.cpp** | ✅ (default local brain) | ❌ | ✅ |
| **MLX (Apple Silicon)** | ✅ | ❌ | ❌ |
| **Custom/OpenAI-compatible** | ✅ | ✅ | ✅ |
| **Fallback Chains** | ✅ | ✅ `hermes fallback` | ✅ `openclaw models fallbacks` |
| **Credential Pools** | ✅ `credential_service.py` | ✅ `hermes auth` (key rotation) | ✅ `openclaw models auth` |
| **Provider Count** | **~10+** | **20+** | **15+** |

---

### 1.9 Tools & Capabilities

| Category | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Total Tools** | **~96** (jaeger-agent) | **60+** | **50+** (core + plugins) |
| **File Operations** | ✅ read, write, patch, search, glob | ✅ | ✅ |
| **Terminal/Shell** | ✅ `terminal`, `execute_code`, background processes | ✅ 6 backends (local, Docker, SSH, Modal, Daytona, Vercel) | ✅ `exec`, sandboxed |
| **Web** | ✅ `web_search`, `web_extract` | ✅ + Tool Gateway (Firecrawl, Browser Use) | ✅ `web_search`, `web_fetch` |
| **Browser Control** | ✅ `browser.py`, computer_use_v1, macos_computer_v1 | ✅ Browser Use (cloud) | ✅ `openclaw browser` (full CDP) |
| **Computer Use (GUI)** | ✅ macOS AX engine, AppleScript, Shortcuts | ✅ cua-driver (macOS/Windows/Linux) | ✅ Via nodes + browser |
| **Vision** | ✅ `vision.py`, image analysis, OCR | ✅ | ✅ `infer image describe` |
| **Image Generation** | ✅ Local + cloud (`plugins/ai_gen/`) | ✅ FAL, Nous Portal | ✅ `infer image generate` |
| **Code Execution** | ✅ `execute_code` (Python) | ✅ `execute_code` | ✅ Code Mode |
| **Email** | ✅ `email.py` (himalaya) | ✅ Email platform | ❌ |
| **Calendar** | ✅ `calendar.py`, `apple_data.py` | ✅ | ❌ |
| **Contacts** | ✅ `contacts.py` | ✅ | ❌ |
| **SMS** | ❌ | ✅ | ✅ |
| **Home Assistant** | ✅ Plugin | ✅ Plugin | ❌ |
| **GitHub** | ✅ Skills (github-*) | ✅ Skills | ✅ Via MCP/plugins |
| **Database** | ❌ | ❌ | ✅ `openclaw database` (SQLite/PostgreSQL porting) |
| **Media Control** | ✅ `media_control.py` | ✅ | ✅ (Spotify plugin) |
| **Minecraft** | ✅ `minecraft.py` | ❌ | ❌ |
| **Kanban/Board** | ✅ `kanban.py` + Dispatcher | ✅ `hermes kanban` | ✅ `openclaw workboard` |
| **Delegation** | ✅ `call_agent.py`, `delegation.py` | ✅ `delegate_task` | ✅ |
| **MCP** | ✅ Client + server (`jaeger mcp`) | ✅ Full MCP management | ✅ `openclaw mcp` |
| **Notifications** | ✅ `notify.py`, `features/notifications/` | ✅ | ✅ |
| **Clipboard** | ✅ `clipboard.py` | ✅ | ✅ |
| **Spotlight/Search** | ✅ `spotify.py` (macOS) | ✅ | ❌ |
| **Shortcuts** | ✅ `shortcuts.py` (macOS) | ✅ | ❌ |
| **System Control** | ✅ `system_control.py` | ✅ | ✅ (via nodes) |

---

### 1.10 Security & Approval Gates

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Approval Gates** | ✅ Per-tool approval, ask-first default | ✅ Command approval, `/approve`, `/deny` | ✅ `openclaw approvals`, exec policy |
| **DM Pairing** | ✅ Channel bindings with admin IDs | ✅ `hermes pairing` (codes, approve/revoke) | ✅ `openclaw pairing` |
| **Allowlists** | ✅ `core/safety/session_trust.py`, admin IDs | ✅ Per-platform allowlists, admin/user tiers | ✅ Two-layer allowlists, group policies |
| **Sandboxing** | ✅ Workspace sandbox (path resolution, read/write gates) | ✅ Container isolation, terminal backends | ✅ `openclaw sandbox` (Docker, per-agent) |
| **Skill Security** | ✅ `skills_guard.py` (dangerous pattern detection) | ✅ Skill audit, `--force` policy blocks | ✅ ClawHub verification (VirusTotal, ClawScan), install policy |
| **Secret Management** | ✅ `credential_service.py`, redaction | ✅ `hermes secrets` (Bitwarden), credential pools | ✅ `openclaw secrets`, SecretRef |
| **Prompt Injection Defense** | ✅ External content wrapping | ✅ | ✅ Untrusted input wrapping |
| **Audit Logging** | ✅ `core/safety/`, audit trail | ✅ Approval history mining | ✅ `openclaw audit`, `openclaw security audit` |
| **TCC Permissions** | ✅ macOS TCC (microphone, camera, accessibility) | ❌ | ❌ |
| **Egress Firewall** | ❌ | ✅ `hermes egress` (iron-proxy) | ✅ SSRF policy |
| **Rate Limiting** | ❌ | ✅ | ✅ Gateway rate limits |
| **OIDC/Auth** | ✅ `features/oidc/` (deprecated), WebUI login | ✅ Dashboard OAuth, Nous Portal OAuth | ✅ Gateway auth, Tailscale Serve |

---

### 1.11 Personality System

| Feature | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **Personas** | ✅ 20 characters (`features/personality/characters/`) | ✅ SOUL.md + `/personality` | ✅ SOUL.md (soul.md spec) |
| **Characters** | Jarvis, Lilith, Assistant, GLaDOS, HAL 9000, Bender, TARS, etc. + work roles | Configurable via SOUL.md | Molty (default) + custom SOUL.md |
| **Per-Channel Personas** | ✅ (`channel_overrides` equivalent) | ✅ Per-channel system prompt overrides | ✅ Per-agent identity |
| **Voice Personality** | ✅ Persona affects TTS voice | ✅ TTS config | ❌ |
| **Lore/Backstory** | ✅ `characters/<name>/lore/` | ❌ | ❌ |
| **Character Cards** | ✅ `card.png` + `SOUL.md` + `character.yaml` | ❌ | ❌ |

---

### 1.12 Deployment Options

| Platform | JaegerAI | Hermes Agent | OpenClaw |
|---|---|---|---|
| **macOS** | ✅ Native (primary target) | ✅ | ✅ Native app + Gateway |
| **Linux** | ⚠️ Via install.sh | ✅ | ✅ |
| **Windows** | ❌ | ✅ Native | ✅ |
| **WSL2** | ❌ | ✅ | ✅ |
| **Docker** | ✅ `jaeger container` (Apple containers) | ✅ Official images | ✅ Official images |
| **iOS** | ❌ | ✅ Hermes Mobile | ✅ iOS node app |
| **Android** | ❌ | ✅ Termux | ✅ Android node app |
| **Raspberry Pi** | ❌ | ✅ | ✅ |
| **Nix/NixOS** | ❌ | ✅ Flake | ✅ |
| **Serverless** | ❌ | ✅ Modal, Daytona, Vercel Sandbox | ❌ |
| **VPS/Cloud** | ⚠️ | ✅ $5 VPS ready | ✅ Fly.io (fly.toml) |
| **NAS** | ✅ (integration target) | ❌ | ✅ Synology Chat plugin |

---

## 2. Strengths & Weaknesses

### 2.1 JaegerAI

#### ✅ What JaegerAI Does Really Well

1. **Robotics Integration** — Native JROS (Jaeger Robot Operating Software) layer for humanoid robots, drones, physical agents. No other project has this.
2. **Proactive World-Model Intelligence** — Acts from sensor events, heartbeat, and background monitoring — not just turn-based prompting. Maintains a checkable world model.
3. **On-Device Trust** — Memory, approvals, audit, raw senses stay on-device/NAS. Cloud is only for LLM calls (named and logged). See `docs/TRUST.md`.
4. **Multi-Surface Clients** — One Gateway (:33418) serves Mac app, Web UI, TUI, VS Code extension, and voice — all sharing sessions and streaming.
5. **Simulation-First Approval** — For physical work: propose → simulate → verify deterministically → human approves → act. Re-plan = re-simulate + re-approve.
6. **Apple-First Engineering** — Native AppKit/WKWebView shell, TCC permission management, MLX support, Shortcuts/Spotlight/Calendar integration.
7. **Voice Pipeline** — Full duplex voice with Kokoro TTS and Whisper STT as engine modules.
8. **Entity Runtime** — True persistent identity surviving restarts, model swaps, and interface changes.
9. **Verification Pipeline** — Independent verification probes (not tool return strings) for effect claims.
10. **YouTube Studio** — Configurable content pipeline (script, voice, rough cut).

#### ❌ What JaegerAI Is Missing

1. **Messaging Platform Breadth** — Only 4 platforms live (Discord, Telegram, iMessage, Home Assistant). Missing WhatsApp, Signal, Matrix, Slack (thin), and 20+ others.
2. **Cross-Platform Apps** — No iOS/Android/Windows desktop apps. macOS-only.
3. **Mobile Nodes** — No way to use phone camera/screen/location as agent tools.
4. **Third-Party Skill Hub** — No community skill marketplace (ClawHub/agentskills.io equivalent).
5. **Memory Files** — SQLite-first, no MEMORY.md/USER.md file-based memory.
6. **Dreaming/Consolidation** — No background memory consolidation.
7. **Hooks System** — No shell-script hooks (like OpenClaw's hooks or Hermes' hooks).
8. **Dedicated CLI Verbs** — Missing `cron`, `logs`, `pairing`, `send`, `browser`, `completion`, `webhook` as CLI verbs.
9. **ACP Server** — No Agent Communication Protocol server (VS Code/Zed integration via ACP).
10. **Multi-Platform Terminal** — TUI is Python-based, not as polished as Hermes' full TUI.
11. **Serverless Deployment** — No Modal/Daytona/Vercel Sandbox support.
12. **Nix Support** — No Nix flake for reproducible installs.

---

### 2.2 Hermes Agent

#### ✅ What Hermes Agent Does Really Well

1. **Self-Improvement Loop** — Creates skills from experience, improves them during use, nudges itself to persist knowledge. "The agent that grows with you."
2. **Messaging Platform Breadth** — 20+ platforms including WhatsApp, Signal, Matrix, Slack, Teams, Google Chat, WeChat, DingTalk, LINE, SMS.
3. **Terminal Backend Flexibility** — 6 backends: local, Docker, SSH, Modal, Daytona, Vercel Sandbox.
4. **Skills Ecosystem** — 171 skills (88 optional), Skills Hub integration, bundles, curator for maintenance.
5. **Nous Portal Integration** — Free hosted model access, Tool Gateway (Firecrawl, Browser Use).
6. **Cross-Platform Desktop** — Electron app for macOS/Windows/Linux.
7. **Mobile Apps** — iOS and Android apps for remote management.
8. **ACP Server** — Native Agent Communication Protocol for IDEs.
9. **Credential Pools** — Key rotation and fallback chains.
10. **Security** — Egress firewall (iron-proxy), security audit, approval history mining.

#### ❌ What Hermes Agent Is Missing

1. **Robotics Integration** — No robot operating system, no physical embodiment layer.
2. **Proactive World Model** — Turn-based, not sensor/heartbeat-driven.
3. **Simulation-First Approval** — No deterministic simulation before physical actions.
4. **On-Device Trust Model** — Designed for cloud-first (Nous Portal).
5. **Multi-Agent Debate** — No Roundtable-style consensus engine.
6. **Avatar System** — Pets only, no animated avatar faces.
7. **YouTube Studio** — No content pipeline.
8. **Native macOS App** — Electron, not native AppKit.
9. **TCC Permission Management** — No macOS-specific permission handling.
10. **Voice Engine Modules** — TTS exists but not as pluggable engine modules.

---

### 2.3 OpenClaw

#### ✅ What OpenClaw Does Really Well

1. **Messaging Platform Breadth** — 30+ channels, the most of any project.
2. **Multi-Device Nodes** — iOS/Android apps that act as remote workers (camera, screen, location, voice).
3. **Gateway Architecture** — Single WebSocket gateway serving all channels simultaneously.
4. **Cross-Platform Apps** — Native macOS, iOS, Android, Windows apps.
5. **ClawHub** — Large community skill marketplace with verification (VirusTotal, ClawScan).
6. **Memory Dreaming** — Background consolidation and grounded backfill.
7. **Hooks System** — Shell-script hooks for automation.
8. **Sandboxing** — Docker-based per-agent sandboxing.
9. **Code Mode** — Advanced code execution patterns.
10. **Worktrees** — Git worktree management for parallel agents.

#### ❌ What OpenClaw Is Missing

1. **Robotics Integration** — No JROS/robot OS layer.
2. **Proactive World Model** — Turn-based, not sensor-driven.
3. **Simulation-First Approval** — No deterministic simulation for physical actions.
4. **On-Device Trust Model** — Cloud-assisted, not strictly on-device.
5. **Persistent Entity Identity** — Session-based, not entity-based.
6. **Avatar System** — Canvas only, no animated faces.
7. **YouTube Studio** — No content pipeline.
8. **Verification Pipeline** — No independent effect verification.
9. **Apple-First Engineering** — No TCC, no native AppKit, no MLX-first approach.
10. **Voice Engine Modules** — Voice is plugin-based, not engine-module architecture.

---

## 3. Gap Analysis: What JaegerAI Needs to Replace Hermes + OpenClaw

### 3.1 Critical Gaps (Must Have)

| Priority | Gap | Impact | Effort | Source |
|---|---|---|---|---|
| 🔴 **P0** | WhatsApp channel | High | Medium | Port from OpenClaw (`extensions/whatsapp`) |
| 🔴 **P0** | Signal channel | High | Medium | Port from OpenClaw (`extensions/signal-cli`) |
| 🔴 **P0** | Matrix channel | Medium | Medium | Port from OpenClaw (`extensions/matrix`) |
| 🔴 **P0** | Slack channel (upgrade from thin) | High | Low | Complete `features/channels/platforms/slack.py` |
| 🟡 **P1** | `jaeger cron` CLI verb | Medium | Low | Wrap existing cron system |
| 🟡 **P1** | `jaeger logs` CLI verb | Medium | Low | Add log viewer |
| 🟡 **P1** | `jaeger pairing` CLI verb | Medium | Low | Add DM pairing management |
| 🟡 **P1** | `jaeger send` CLI verb | Medium | Low | Add one-shot message sender |
| 🟡 **P1** | `jaeger browser` CLI verb | Medium | Medium | Expose browser tools |
| 🟡 **P1** | Shell completion (`jaeger completion`) | Low | Low | Add bash/zsh/fish completion |
| 🟡 **P1** | iOS/Android node apps | High | High | Build mobile node clients |
| 🟡 **P1** | MEMORY.md / USER.md files | Medium | Low | Add file-based memory layer |
| 🟡 **P1** | Hooks system | Medium | Medium | Port from OpenClaw |
| 🟢 **P2** | Skills Hub integration | Medium | Medium | Connect to agentskills.io or ClawHub |
| 🟢 **P2** | ACP server | Medium | Medium | Implement ACP protocol |
| 🟢 **P2** | Memory dreaming | Low | High | Background consolidation |
| 🟢 **P2** | Windows/Linux native apps | Low | High | Port macOS shell |
| 🟢 **P2** | Docker images | Medium | Low | Create official Dockerfiles |
| 🟢 **P2** | Nix flake | Low | Low | Create reproducible install |
| 🟢 **P2** | Serverless (Modal/Daytona) | Low | High | Add serverless backends |

### 3.2 Feature Parity Score

| Category | JaegerAI | Hermes | OpenClaw | Parity % |
|---|---|---|---|---|
| CLI Commands | 40+ | 55+ | 80+ | 50-70% |
| Messaging Platforms | 4 live + 3 planned | 20+ | 30+ | 20-25% |
| User Interfaces | 7 | 6 | 6 | 80-90% |
| Memory Systems | 5-class taxonomy | SQLite + files | SQLite + files + dreaming | 70% |
| Skills | 107 | 171 | Bundled + ClawHub | 60% |
| Automation | 10+ mechanisms | 8+ | 10+ | 80% |
| Multi-Agent | 6 features | 4 | 5 | 90% |
| Model Providers | 10+ | 20+ | 15+ | 60% |
| Tools | 96 | 60+ | 50+ | 100%+ |
| Security | 8 features | 10+ | 10+ | 70% |
| Personality | 20 characters + lore | SOUL.md | SOUL.md | 100%+ |
| Deployment | macOS, Linux, Docker | Universal | Universal | 40% |
| **Overall Parity** | | | | **65-70%** |

---

## 4. Migration Path: Hermes/OpenClaw → JaegerAI

### 4.1 Data Migration

| Data Type | Source | Target | Method |
|---|---|---|---|
| **Sessions/Conversations** | Hermes `state.db`, OpenClaw `openclaw.sqlite` | JaegerAI `gateway_sessions.sqlite3` | Use `jaeger sessions import` (create this) |
| **Memory/Facts** | Hermes `MEMORY.md`, OpenClaw `MEMORY.md` | JaegerAI SemanticMemory | Parse markdown → extract facts → store |
| **User Profile** | Hermes `USER.md`, OpenClaw `USER.md` | JaegerAI instance identity | Import into `identity.yaml` |
| **Skills** | Hermes `~/.hermes/skills/`, OpenClaw `~/.openclaw/skills/` | JaegerAI `packages/jaeger-agent/jaeger_agent/skills/` | Copy compatible SKILL.md files |
| **Cron Jobs** | Hermes `cron/`, OpenClaw `cron.json` | JaegerAI schedules table | Migrate via unified scheduler migration |
| **Channel Configs** | Hermes `config.yaml`, OpenClaw `openclaw.json` | JaegerAI `config.yaml` per instance | Manual mapping or migration script |
| **API Keys/Credentials** | Hermes keychain, OpenClaw config | JaegerAI `credential_service.py` | Import to Keychain |

### 4.2 Configuration Migration Script

```bash
# Create: scripts/migrate-from-hermes.sh
#!/bin/bash
# Migrate Hermes Agent data to JaegerAI

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
JAEGER_HOME="${JAEGER_HOME:-$HOME/.jaeger}"

# 1. Create JaegerAI instance
jaeger agent create --name "migrated" --non-interactive

# 2. Import sessions
python3 -c "
from jaeger_ai.core.sessions import import_hermes_sessions
import_hermes_sessions('$HERMES_HOME/state.db', '$JAEGER_HOME/instances/migrated/')
"

# 3. Import memory
python3 -c "
from jaeger_ai.core.memory import import_memory_file
import_memory_file('$HERMES_HOME/MEMORY.md', instance='migrated')
"

# 4. Copy skills
cp -r "$HERMES_HOME/skills/"* "$JAEGER_HOME/instances/migrated/skills/" 2>/dev/null || true

# 5. Migrate cron jobs
jaeger tasks migrate --from-hermes "$HERMES_HOME"

echo "Migration complete. Review and test:"
echo "  jaeger agent use migrated"
echo "  jaeger"
```

### 4.3 Channel Migration

| Platform | Action |
|---|---|
| **Discord** | Reuse bot token, update webhook URL to JaegerAI Gateway |
| **Telegram** | Reuse bot token, update webhook URL to JaegerAI Gateway |
| **iMessage** | Reuse BlueBubbles/Photon config |
| **Slack** | Create new Slack app, use Socket Mode with JaegerAI |
| **WhatsApp** | Port OpenClaw extension → JaegerAI plugin (P0) |
| **Signal** | Port OpenClaw extension → JaegerAI plugin (P0) |

---

## 5. Recommendation: Can JaegerAI Replace Hermes + OpenClaw?

### 5.1 Verdict

**Yes, with conditions.** JaegerAI can replace Hermes Agent and OpenClaw for **65-70% of use cases** today, and **90%+** once the P0/P1 gaps are filled.

### 5.2 Use Case Coverage

| Use Case | JaegerAI | Hermes | OpenClaw | Winner |
|---|---|---|---|---|
| **Personal AI assistant (chat)** | ✅ | ✅ | ✅ | Tie |
| **Coding agent (files, terminal, web)** | ✅ | ✅ | ✅ | Tie |
| **Multi-channel messaging (WhatsApp, Telegram, etc.)** | ⚠️ 4 platforms | ✅ 20+ | ✅ 30+ | Hermes/OpenClaw |
| **Proactive/heartbeat automation** | ✅ Superior | ⚠️ | ⚠️ | **JaegerAI** |
| **Robotics/physical embodiment** | ✅ **Unique** | ❌ | ❌ | **JaegerAI** |
| **On-device trust/privacy** | ✅ **Superior** | ⚠️ | ⚠️ | **JaegerAI** |
| **Multi-surface clients (Mac/Web/TUI/IDE)** | ✅ **Superior** | ⚠️ | ⚠️ | **JaegerAI** |
| **Simulation-first approval (physical work)** | ✅ **Unique** | ❌ | ❌ | **JaegerAI** |
| **Skills ecosystem** | ⚠️ 107 | ✅ 171 | ✅ ClawHub | Hermes/OpenClaw |
| **Self-improving skills** | ✅ | ✅ **Superior** | ✅ | Hermes |
| **Cross-platform apps (iOS/Android/Windows)** | ❌ | ✅ | ✅ **Superior** | OpenClaw |
| **Mobile nodes (camera/screen as tools)** | ❌ | ⚠️ | ✅ **Unique** | OpenClaw |
| **Content creation (YouTube Studio)** | ✅ **Unique** | ❌ | ❌ | **JaegerAI** |
| **Business operations (finance, missions)** | ✅ | ⚠️ | ⚠️ | **JaegerAI** |

### 5.3 Timeline to Full Replacement

| Phase | Timeline | Deliverables | Coverage |
|---|---|---|---|
| **Phase 1: Critical Messaging** | 2-4 weeks | WhatsApp, Signal, Matrix, Slack upgrade | 80% |
| **Phase 2: CLI Parity** | 1-2 weeks | `cron`, `logs`, `pairing`, `send`, `browser`, `completion` verbs | 85% |
| **Phase 3: Mobile Apps** | 2-3 months | iOS/Android node apps | 90% |
| **Phase 4: Skills Hub** | 1-2 months | ClawHub/agentskills.io integration | 92% |
| **Phase 5: Cross-Platform** | 3-6 months | Windows/Linux native apps, Nix, Docker | 95% |
| **Phase 6: Advanced** | 6+ months | ACP, dreaming, serverless, hooks | 98% |

### 5.4 Recommended Approach: Hybrid → Full Migration

**Step 1: Run in Parallel (Now)**
- Keep Hermes/OpenClaw for messaging-heavy workflows
- Use JaegerAI for robotics, proactive automation, YouTube Studio, business ops

**Step 2: Migrate Data (1-2 weeks)**
- Run migration scripts
- Test sessions, memory, skills in JaegerAI

**Step 3: Fill P0 Gaps (2-4 weeks)**
- Port WhatsApp, Signal, Matrix from OpenClaw
- Upgrade Slack to full implementation

**Step 4: Migrate Channels (1 week)**
- Move Discord, Telegram, iMessage to JaegerAI
- Test thoroughly

**Step 5: Decommission (Ongoing)**
- Keep Hermes/OpenClaw as fallback for 1 month
- Monitor for missing features
- Fully switch when comfortable

### 5.5 Final Recommendation

| Scenario | Recommendation |
|---|---|
| **Robotics focus** | ✅ **JaegerAI now** — unique advantage |
| **Proactive automation** | ✅ **JaegerAI now** — superior heartbeat/world model |
| **YouTube/business ops** | ✅ **JaegerAI now** — unique content pipeline |
| **Heavy messaging (WhatsApp/Signal)** | 🟡 **Hybrid** — until P0 gaps filled |
| **Mobile-first (phone as tool)** | 🟡 **Hybrid** — until mobile apps built |
| **Skills-heavy workflows** | 🟡 **Hybrid** — until Skills Hub integration |
| **Cross-platform team** | 🔴 **Keep OpenClaw/Hermes** — for now |
| **Everything above combined** | 🟡 **JaegerAI + fill P0/P1 gaps in 4-6 weeks** |

---

## 6. Action Items

### Immediate (This Week)
1. [ ] Create `scripts/migrate-from-hermes.sh`
2. [ ] Create `scripts/migrate-from-openclaw.sh`
3. [ ] Add `jaeger cron` CLI verb
4. [ ] Add `jaeger logs` CLI verb
5. [ ] Add `jaeger pairing` CLI verb
6. [ ] Add `jaeger completion` shell scripts

### Short Term (2-4 Weeks)
7. [ ] Port WhatsApp from OpenClaw
8. [ ] Port Signal from OpenClaw
9. [ ] Port Matrix from OpenClaw
10. [ ] Upgrade Slack to full implementation
11. [ ] Add `jaeger send` CLI verb
12. [ ] Add `jaeger browser` CLI verb
13. [ ] Add MEMORY.md / USER.md file support

### Medium Term (1-3 Months)
14. [ ] Build iOS node app
15. [ ] Build Android node app
16. [ ] Integrate with ClawHub or agentskills.io
17. [ ] Add hooks system
18. [ ] Add ACP server

### Long Term (3-6+ Months)
19. [ ] Windows native app
20. [ ] Linux native app
21. [ ] Memory dreaming/consolidation
22. [ ] Serverless deployment (Modal/Daytona)
23. [ ] Nix flake

---

*Comparison completed: 2026-10-25*
*For questions: GitHub Issues or Discussions*
