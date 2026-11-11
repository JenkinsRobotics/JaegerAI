# Standalone foundations

Jaeger's canonical macOS shell hosts the same React UI as the authenticated web client. The standalone app includes its Python interpreter and dependency environment, source snapshot, compiled UI, Node, Chromium and Steel Browser. Operator data and credentials stay in the existing operator state directory. Cloud model providers still require an account and network connection; optional external coding products remain integrations.

## What this branch landed

| Area | Change |
| --- | --- |
| Model feature passport | `jaeger_ai/core/models/model_features.py` — open weights, tools, thinking mode, effort ladder; inventory and cognition profiles consume it |
| Fallback model controls | Selecting a configured alternative keeps that row's ctx / max_tokens / timeout / reasoning_effort / base_url |
| Subscription CLIs | Gemini + Antigravity (`agy`) discovery; CLI backends remain browser/subscription login, not Jaeger API keys |
| IDE host LM bridge | Extension `0.4.2` `host-lm-bridge.js` exposes VS Code / Cursor / Antigravity signed-in models on loopback; Gateway never sees host credentials |
| Lifecycle | launchd owns Gateway lifetime; quitting the Mac menu-bar app does not tear the stack down |
| Packaging | Standalone app bundles runtime; operator state stays under `~/.jaeger` |

## Ownership

| Area | Owner | Notes |
| --- | --- | --- |
| Shell, chat, panels | Shared React UI + Swift host | Same UI as web client |
| Sessions, approvals, events | Jaeger Gateway (`:33418`) | Sole execution authority |
| Browser | Gateway-owned Steel / Chromium per conversation | Agent tool + MCP surface |
| Models | `core/models/*` + request policy | Feature passport is descriptive only — never invents certification PASS |
| IDE bridge | `interfaces/ide/host-lm-bridge.js` + `features/webui/api/cli_providers.py` | Token only under `~/.jaeger/run/` mode 0600 |

## Validation

- Unit: model configuration, request policy, model features, CLI provider / host bridge tests
- IDE: install extension ≥ 0.4.2, run **Jaeger: Allow Host Models for Jaeger**, confirm models appear as `cli:vscode:*`
- Standalone: relocate app, confirm imports resolve from bundle, Gateway health on `127.0.0.1:33418`

## Not in scope here

- Replacing Gateway, memory, or authority kernel
- Copying live operator data into the app bundle
- Treating archived WIP branches as release requirements
