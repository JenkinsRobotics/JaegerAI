# Jaeger AI NexusUI app: handoff (2026-11-27)

## What this is

A second desktop UI for Jaeger AI, beside the Swift Mac app (`jaeger_ai/interfaces/macos-shell`) and the WebUI
(`jaeger_ai/interfaces/ui`, :8790). Neither of those was changed. It gives Jaeger AI a working avatar: a face that
speaks every reply in Jaeger Agent's voice and hears you with Jaeger Agent's hearing. The brain is Jaeger AI's own
Gateway (:33418).

It follows the NexusUI desktop pattern used by Jaeger Avatar and Jaeger Omni: a Python server, a React + TypeScript +
Vite screen, and a pywebview window (`--browser` serves the same screen). The look is copied, not imported: Aether
tokens, Omni's screen, Jaeger Avatar's flat face renderer, and the NexusUI app shell (`web/src/app-shell/`, from
`VisualReactpy/framework/nexusui/app_shell`: Aether Studio's sidebar and status bar, no header).

**Faces (2026-11-27).** A picker on the stage switches between Jaeger's flat face and **Vita**, the anime VRM avatar.
- Vita's pack is copied whole from Jaeger Avatar (`avatars/vita`, 0.2.2, from JaegerAvatar dev 31e8a09), including
  its LICENSE.txt and MODEL-METADATA.json. The model is VRoid AvatarSample_F (CC0); the persona is Apache-2.0.
- She is drawn with Jaeger Avatar's VRM renderer, copied into `web/src/vrm/`: three r187 and three-vrm 3.5.5 from npm,
  loaded only when a VRM face is worn.
- Her behaviour: idle motion and blinks come from the rig. Her expression follows the mood: thinking, listening, and
  laughing when a reply has `[laugh]`. Her lips follow Jaeger Avatar's analysis of the Kokoro voice as it plays.
- Picking her makes her character sheet (`avatar.yaml`) ride on each message as an `[In character: …]` line. The
  chat never shows that line, and the Gateway's system prompt is untouched. Her voice is the pack's `af_heart`, the
  same as Jaeger's.
- `faces.py` lists the faces. Any VRM pack dropped into `avatars/` shows up in the picker.

## Run it (this Mac)

1. A model the Gateway can use. The Gateway's default (`mistral-large-4:cloud` on Ollama) had no credits on
   2026-11-27, so testing used the local Qwen3-1.7B GGUF:
   ```bash
   llama-server -m ~/.cache/jaeger/models/Qwen_Qwen3-1.7B-Q4_K_M.gguf --host 127.0.0.1 --port 8091 -c 8192 --jinja --alias qwen3-1.7b
   ```
2. The Gateway, with its own state folder so a real `~/.jaeger` is not touched:
   ```bash
   JAEGER_STATE_DIR=~/.jaeger/dev-nexus-state JAEGER_GATEWAY_OLLAMA_MODEL=openai:qwen3-1.7b \
   OPENAI_BASE_URL=http://127.0.0.1:8091/v1 OPENAI_API_KEY=local python -m jaeger_ai start
   ```
3. The app. Its Python needs `pywebview` (6.2.1 tested). `JAEGER_VOICE_PYTHON` is a Python that has Jaeger Agent
   1.2.0 with jaeger-kokoro-tts 0.14.0 and jaeger-whisper-stt 0.14.0; on this Mac that is Jaeger Avatar's agent venv.
   ```bash
   JAEGER_VOICE_PYTHON=~/GITHUB/JaegerAvatar/.agent-venv/bin/python JAEGER_STATE_DIR=~/.jaeger/dev-nexus-state \
   python -m jaeger_ai.interfaces.nexus            # add --browser for http://127.0.0.1:8795
   ```
   On first run it builds the screen from `web/` into `~/.cache/jaeger/nexus-ui/dist`, outside the repo (Golden
   Rule 1). `--build` rebuilds it. Without `JAEGER_VOICE_PYTHON` the app still chats, silently, and says why.

## How it works

| File | Job |
|---|---|
| `__main__.py` | Starts everything; opens the window, the Quick Ask pill and the menu-bar item |
| `gateway.py` | Gateway client. `Bridge` follows the main chat's SSE stream (`/v1/sessions/{sid}/events`), sends runs (`POST …/runs`) and turns Gateway events into the screen's chat events |
| `voice.py` / `voice_worker.py` | The avatar's voice and hearing. The worker runs Jaeger Agent's `SpeechRuntime` (Kokoro + Whisper modules) on `JAEGER_VOICE_PYTHON`, as JSON lines over stdio. Each finished reply is spoken *after* the model is done (one GPU job at a time on this Mac) |
| `serve.py` | The screen's server: `/ui/config`, `/health`, `/agent/*`, `/shell/*`. Every POST needs `X-Jaeger` and a loopback Host |
| `shell.py` | What the Swift shell does natively: status monitors, the Droid, Mac and stack actions, notifications, deep links, clipboard, permissions |
| `native.py` | macOS menu-bar item (the same menus as the Swift `StatusItemController`) and the global hotkey (PyObjC) |
| `window.py` | pywebview window plus a mic/camera grant for its own page (copied from Omni) |
| `look.json` | Jaeger's frozen screen look. The character owns it; replace the file to change the look |
| `faces.py`, `avatars/` | The faces to wear: Jaeger's flat look and each VRM pack (Vita), with its persona and voice; `/avatars/*` serves their files |
| `web/` | The screen. `main.tsx` (the app shell's sidebar, avatar + chat), `Chat.tsx`, `Shell.tsx` (Status, Tasks, Droid, Mac, Settings), `Stage.tsx` + `face/` (Jaeger Avatar's flat face), `voice.ts` (plays her voice; the mouth follows its loudness), `mic.ts` (one clip per press) |
| `INVENTORY.md` | Every Swift UI element and its counterpart here, with what was checked |

Measured on this Mac:
- Voice: Kokoro 0.14.0 `af_heart` on MLX made 3.55 s of speech, laugh included, in 350 ms.
- Hearing: Whisper large-v3-turbo on Metal heard that clip back correctly in 534 ms.
- Worker load: 9 s.
- Model: Qwen3-1.7B took about 6 s per reply here.

## Checks

- `python -m jaeger_ai.interfaces.nexus.shell`: deep-link rules, using the Swift JaegerDeepLinkTests cases.
- `python -m jaeger_ai.interfaces.nexus.native`: hotkey parsing.
- `python -m jaeger_ai.interfaces.nexus.voice`: a silent voice says why.
- `python -m jaeger_ai.interfaces.nexus.faces`: the packs read, files stay inside `avatars/`, a persona never shows in the chat.
- `cd web && npm test`: chat events and audio conversion (11 tests).
- The repo's backend suite (`scripts/verify.sh backend`): 223 passed, 2 failed, neither from this app. Seatbelt only
  lets Python run from `~/.jaeger/venv` and this run used another venv; the other failure is xcodebuild log noise in
  `execute_code`'s output.

## Left to do

1. **Speak sentence by sentence.** Today the whole reply is spoken once the Gateway's run completes (simple, one GPU
   job at a time). For a faster first sound, voice each sentence as `text.delta` streams in, behind a GPU lock.
2. **Mood from the model.** The face shows thinking, listening and neutral. The Gateway sends no feelings yet, so
   there are no joy or sad faces. Jaeger Agent's `avatar` tool (feeling per reply) is the pattern to follow.
3. **Laughs.** Kokoro plays a recorded laugh for `[laugh]` (af_heart's sound bank only). The Gateway's prompt does
   not ask for it yet; following the "no agent delay from character text" rule, it would ride on the turn, not the
   system prompt.
4. **Duplex.** Half duplex: press Mic, speak, press again; the mic stays shut while she speaks. Open-mic or quasi
   duplex (talk over her) is Jaeger Agent's `body/loop.py` `duplex()`. It needs the live mic stream, not clips.
5. **Vita, next steps.**
   - Her performance tags (`[wave]`, `[joy]`) and the pack's sound lines are not used yet. Jaeger Avatar's `brain.js`
     parser is the pattern to copy.
   - A per-face Kokoro voice needs the voice worker to take a voice per `say`; today both faces use `af_heart`.
   - Speech reads `*hums softly*` stage directions aloud. Strip those before `say`.
   - `model.vrm` adds 14 MB to the repo.
6. **The Swift inventory.** `INVENTORY.md` has 63 rows (the Swift app's ~70 elements, a few grouped): 22 checked, 37 built but not exercised (some
   held back on purpose because they change the Mac: stack restart, Lock Mac, Droid wake, launch at login), 4 with
   no exact equivalent. The Gateway on master has no `/v1/live/tasks`, so live tasks and their notifications are off
   in both apps.
7. **Jaeger AI on Jaeger Agent v1.2.0, as its agent engine.** Not started, waiting for the owner's OK. Findings and
   plan, in short:
   - GitHub master (dde9b24, the "clean-slate" rewrite) deleted the old diverged `packages/jaeger-agent`. The
     Gateway runs each turn on its own loop:
     `RunCoordinator → ModularGatewayRuntime._execute_turn (runtime.py:1804) → jaeger_loop.AgentLoop`.
   - Jaeger Agent v1.2.0 (`JenkinsRobotics/jaeger-module-agent`, cb7082b) has no HTTP server. A host calls
     `DefaultAgentRuntime.run_turn(text, session_key, on_delta)`, with tool events through `AgentCallbacks`.
   - Doctrine: `packages/jaeger-*` must never import `jaeger_agent`; only `jaeger_ai/` may.
   - Plan:
     - A small engine seam in `jaeger-gateway` (a callable defined in `jaeger-contracts`).
     - A Jaeger Agent engine in `jaeger_ai/` that maps the agent's callbacks to the Gateway's SSE events
       (`text.delta`, `thinking.delta`, `tool.*`, `run.*`).
     - Jaeger Agent v1.2.0 + jaeger-os as an optional extra.
     - A/B the same prompts on both engines before switching the default.
     - Second pass: tools and approvals through the Gateway's PolicyEngine.
     - Third pass: Jaeger Agent's voice replaces the Gateway's whisper-cli path.
   - Conflicts to settle: two tool registries, two model routers, two memory stores, two transcripts (the Gateway
     store replays history each turn; Jaeger Agent keeps its own per session).
8. **Upstream issues seen on master.**
   - `scripts/setup.sh --profile core` installs a Gateway that cannot import (it needs `jaeger_business`, which is
     only in the business profile).
   - `dev/benchmark/scenarios.py` imports `jaeger_ai.main`, which master deleted.
   - `swe_runner.py` needs `core.workspace.get_project_root`, which is not in Jaeger Agent v1.2.0.
   - The Swift Droid menu calls `/v1/droid/*` with no token; that fails if the Gateway requires one.
