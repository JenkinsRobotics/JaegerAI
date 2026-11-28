# Third-Party Notices & Attributions

JaegerAI is licensed under the Apache License, Version 2.0.

This repository incorporates adapted modular components, specifications, and reference assets from the following permissively licensed open-source projects (all MIT or Apache-2.0 compatible):

| Project | License | Adapted Scope |
|---|---|---|
| **Aider** (`Aider-AI/aider`) | Apache-2.0 | Tree-sitter + PageRank RepoMap (`jaeger-repomap`), fuzzy search/replace & patch editors, tree-sitter linter, git repo utilities |
| **Hermes Agent** (`NousResearch/hermes-agent`) | MIT | Tool schema sanitization, API error classifier, message sanitization, secret redaction, dangerous-command detection, MCP 2.x client, skills guard & manager, ACP adapter |
| **Pydantic AI** (`pydantic/pydantic-ai`) | MIT | Streaming parts manager, prompt-cache collapse detection, SpanTree agentic evaluators, CSRF/Host hardening |
| **LangGraph** (`langchain-ai/langgraph`) | MIT | Durable SQLite Pregel execution patterns, multitask & disconnect strategies, resumable streaming |
| **AG2** (`ag2ai/ag2`) | Apache-2.0 | A2UI / AG-UI / MCP-UI protocols, compaction verification, ephemeral statusbar middleware, realtime voice cascade |
| **Cline** (`cline/cline`) | Apache-2.0 | `@cline/ui` React 19 chat, tool summary, diff, approval, composer, and Mermaid components; transactional checkpoint-restore algorithm |
| **Goose** (`block/goose`) | Apache-2.0 | React 19 MCP Apps host, Context X-Ray, ElicitationRequest, CronPicker, JsonSchemaForm, threat & egress security patterns |
| **OpenHands** (`All-Hands-AI/OpenHands`) | MIT | Streaming delta batcher, virtual scroll anchoring, terminal/files/MCP UI widgets, Cmd+K command menu, WebSocket reconnect hooks |
| **OpenCode** (`anomalyco/opencode`) | MIT | `patchmark` zero-dependency streaming Markdown engine |
| **AutoGPT** (`Significant-Gravitas/AutoGPT`) | MIT | Visual workflow editor (`FlowEditor` / `JSBeads`), `ArtifactPanel`, `ChatMinimap`, `SoulDrawer`, dry-run simulator, 3-way `SKILL.md` merge |
| **OpenAI Codex** (`openai/codex`) | Apache-2.0 | macOS Seatbelt `.sbpl` sandbox profiles, turn diff tracking, optional CLI helpers |
| **Gemini CLI** (`google-gemini/gemini-cli`) | Apache-2.0 | Tiered `.toml` policy profiles, macOS `.sb` Seatbelt profiles, tree-sitter bash AST rules, React DevTools inspector |
| **SWE-agent** (`SWE-agent/SWE-agent`) | MIT | History processors (Anthropic `cache_control` + observation elision), AST window expander & delta-lint diffing |
| **MetaGPT** (`geekan/MetaGPT`) | MIT | Headless Mineflayer Minecraft embodiment bridge (`jaeger-embodiment-minecraft`), `@exp_cache` trajectory cache |
| **CrewAI** (`crewAIInc/crewAI`) | MIT | Adaptive memory recall, versioned artifacts, `llm_overlay` ContextVar |
| **Agno** (`agno-agi/agno`) | Apache-2.0 / MPL-2.0 *(patterns/specs only where applicable)* | Learning stores & curator patterns, safe CEL workflow expression evaluation |
| **smolagents** (`huggingface/smolagents`) | Apache-2.0 | Rolling multimodal frame pruning, periodic planning step, `SafeSerializer` |
| **Amica** (`semperai/amica`) | MIT | Studio VRM 0.x/1.0 Three.js rig patterns (3-point studio lighting, ACESFilmic, AutoBlink, pointer eye saccades, relaxed stance solver, emotion & viseme lip-sync blending) |
| **OpenReel Video** (`Augani/openreel-video`) | MIT | Multi-track NLE studio timeline component (`StudioTimeline`) for YouTube & media production |
| **Voyager** (`MineDojo/Voyager`) | MIT | Headless Mineflayer Minecraft JS control primitives (`control_primitives/*.js`) and lifelong skill-library pattern |
| **Pixel Agents** (`pixel-agents-hq/pixel-agents`) | MIT | 2D HTML5 Canvas pixel-art virtual office architecture, BFS tile-map pathfinding, sprite state machine, and Matrix spawn visuals (`@jaeger/ui-office`) |
| **Mindcraft** (`mindcraft-bots/mindcraft`) | MIT | Minecraft survival reflex modes (`self_preservation`, `auto_eat`, `self_defense`, `unstuck`, `follow_player`) and deterministic co-op companion skills (`jaeger-embodiment-minecraft`) |
| **OpenClaw** (`openclaw/openclaw`) | MIT | Ambient room context buffering, mention gating, and bot-loop protection patterns for Discord (`jaeger-channels/discord_guard.py`) |
| **Open-LLM-VTuber** (`Open-LLM-VTuber/Open-LLM-VTuber`) | MIT | First-comma streaming TTS chunking, `[expression]` cue extraction, and inner-thought/action speech stripping (`jaeger-realtime/speech_prep.py`) |
| **Project AIRI** (`moeru-ai/airi`) | MIT | Natural technical speech preprocessing (URLs, file paths, currency, math), pause-aware turn-end judgement (`jaeger-realtime/speech_prep.py`), and sensitive-app computer-use deny-list + 4-stage audit record (`jaeger-macos/computer_guard.py`) |
| **llmfit** (`AlexsJones/llmfit`) | MIT | Hardware-aware unified-RAM model fit scoring patterns (`jaeger-models/hwfit.py`) |
| **Tongyi DeepResearch** (`Alibaba-NLP/DeepResearch`) | Apache-2.0 | Multi-step query planning, source extraction, and cited synthesis pipeline patterns (`jaeger-orchestration/deep_research.py`) |

Full upstream license texts are preserved in each donor module's header or `LICENSE` attribution block when extracted.
