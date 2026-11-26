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

Full upstream license texts are preserved in each donor module's header or `LICENSE` attribution block when extracted.
