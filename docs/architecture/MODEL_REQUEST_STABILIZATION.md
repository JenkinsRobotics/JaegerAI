# Model request stabilization

The Gateway remains the sole owner of admission, conversations, approvals and durable events. EntityRuntime owns agent execution and the optional in-process model. Provider adapters own inference and cancellation. No second router service, memory store, executor or event bus is introduced.

## Ownership and migration

| Area | Evidence / prior owner | Action | Validation |
|---|---|---|---|
| Direct Chat, voice and images | Gateway `_ollama_chat` hardwired Ollama, discarded provider, conditionally streamed | Replace with `_model_chat` and shared `models/completion.py`; retain provider identity and the existing adapters | Gateway history, provider pair, delta, cancellation and attachment tests |
| Model destinations | Current-message keyword routing plus unguarded assembled history | `request_policy.py` checks the assembled payload at every guarded primary/fallback call; explicit local-only never routes externally through these model consumers | Synthetic private history, image, tool output and local-only assertions |
| Agent image questions | Gateway heuristic redirected into a tool-less lane | Retain EntityRuntime execution and its tools; explicit Chat mode uses typed image input | Image question/action owner-path regression |
| Missing executor | Cognition handler returned fabricated success | Report execution unavailable, no action and no model invocation | Missing-runtime regression |
| Local engine | No direct-chat local owner | Reuse one cached engine in EntityRuntime; no implicit download; changing loaded configuration requires restart | Unconfigured identity rejects before resolution |
| Ollama allocation | Stack inferred locality from model suffix alone | Require enabled local Ollama provider; one loaded model, one inference, 32K derived context, 5-minute retention; explicit service settings remain authoritative | CLI/cloud isolation and allocation-bound tests |
| Setup and doctor | Local model recommended as if required | Cloud/CLI wizard choice, optional explicit local choice, unconfigured identity before selection; external doctor does not require GGUF | Setup and preflight tests |
| Browser lifecycle | Session deletion left its browser alive | Close the owned worker before deleting the session; remove dead pool entries | Session deletion ordering and browser workspace tests |
| Fallback credentials | Global pipeline state and primary credential reused for alternatives | Read admitted client configuration; resolve target provider credentials; unavailable alternatives cannot disable the primary | Provider credential regression |
| Release | Existing dist and dirty source accepted | Fresh UI build from a clean revision, asset hashes, UI/typecheck/native gates | Candidate manifest and installed hash verification |

Retained paths: Gateway, native shell, shared React UI, WebUI authentication/proxy, browser runtime, model adapters, optional local backends, skills, and explicitly gated legacy execution. Removed only the obsolete direct Ollama implementation and its unused vision-routing helpers. No operator data migration is required.

## Behavioral contract

- The selected provider/model pair is retained across Chat and Agent. Agent images keep tools; both modes require an adapter with image input support. An unsupported image never triggers a hidden cloud fallback.
- Every model-only answer uses incremental deltas when supplied by its adapter. Interrupted or truncated transport is a failure; partial text may remain visible but is not a successful terminal receipt.
- A `model.route` event records the selected route. The terminal result records its provider/model; provider-reported identity is retained separately when available. A selected route is not proof of successful inference.
- Local-only history stays constrained on subsequent turns and auxiliary summary/organization requests. Egress checks cover assembled text, including previous turns and tool results. They are a conservative heuristic, not a complete sensitive-data detector. Image pixels are not classified; an explicit local-only constraint still prevents external image dispatch.
- A missing local capability produces an actionable error. Neither setup nor a failed cloud call silently downloads Gemma or allocates another local model.
- Fallback models are only explicitly configured alternatives. Selection is not yet a quality-ranking or model-voting system.

## Qualification

Run `scripts/verify.sh`, including the shared UI/typecheck, macOS shell, provider adapters, request-policy, setup, resource and existing durability suites. Product tests and reusable-package tests run in separate processes because their fixtures establish different state roots.

Build a clean revision with `scripts/build-standalone-macos.py`. Check the built artifact's dependency and UI manifest, imports without the developer checkout, signing, and browser runtime. Installed acceptance must separately prove a real streamed provider response, a tool receipt, saved history, pane combinations, browser operation, and stop/reconnect. A passing source test or successful launch is not installed acceptance.

Further architecture work remains separate: measured automatic model selection, explicit model roles per bot, evaluator/worker teams, pressure-driven scheduling and richer capability inventory. These should use this same admission and execution ownership.
