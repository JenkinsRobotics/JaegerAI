# JaegerAI — AI stack and dependencies

Centre: jaeger-agent + JaegerAI on top. MODEL != AGENT. Swap the model, provider, or device, and the agent, memory, and approvals stay.

## Reusable packages (the stack itself)

- **JaegerAI** — standalone intelligence stack, the application layer on top
- **jaeger-agent** — reusable headless agent brain: loop, ~96 tools, 107 skills, cognition, SQLite memory, sandbox, verify gate
- **JaegerOS** — operating framework for robots, drones, and digital agents: transport/nodes/topics, body contract, local-first on Apple Silicon / Jetson Orin
- **JaegerKokoroTTS / JaegerWhisperSTT** — speech out / speech in, as engine modules
- **Your NAS / file storage** — business / content / project home, system of record for files (configured per-instance)

## jaeger-agent dependencies, from its pyproject.toml, when possible

Base: jaeger-os >=0.9.0, llama-cpp-python >=0.3 (default local brain), jinja2 >=3.1, croniter >=2.0. Python >=3.11, <3.14.

Optional extras: anthropic, openai (wire format, also LM Studio / Ollama / llama.cpp server / vLLM), mlx (mlx-lm, mlx-vlm), embeddings (sentence-transformers, sqlite-vec, numpy), vision (torch, transformers, pillow), image_gen (diffusers), multimodal/audio (numpy, scipy, sounddevice, soundfile, pywhispercpp, kokoro, onnxruntime, plus pyaec for duplex), browser (playwright), ocr_macos (pyobjc Vision/Quartz/Cocoa), search (ddgs, duckduckgo-search).

## Later, not dependencies yet

PDDL + Fast Downward, Z3/SMT, DreamerV3 / V-JEPA family (imagination only, never the safety case), MERT / MusicFM, StreamingVLM / LiveVLM, OpenVLA / LeRobot / pi0, PX4 SITL, Isaac Sim / Gazebo / MuJoCo / MoveIt (reference only — JROS is our layer).

External ROS 2 / Nav2 / MoveIt are reference only, not our stack. Do not list them as our stack.

## Rule

JaegerAI adds project-specific tools on top of jaeger-agent. It does not rebuild a loop, memory store, tool executor, or skill loader. New JaegerAI work plugs into jaeger-agent, it does not copy a second brain, graph, or gate.

Full draft list, with versions and notes, was prepared in the workspace on 2026-10-22. This file is the in-repo version to keep with the code. If a dependency in pyproject.toml is not in this file, that is a bug in this file, not in pyproject.toml.
