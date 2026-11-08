# Chat continuity and provider boundaries

Jaeger Gateway owns conversations, request admission, context assembly,
execution, approvals, and durable events. Phone/WebUI, native Mac and IDE
clients attach to those identities. Ollama Cloud supplies inference; swapping
the model must not replace the session owner or create a second agent loop.

## Implemented connection contract

- `/chat?session=<id>` identifies the exact conversation. The WebUI validates
  it through the authenticated Gateway before attaching. An unavailable linked
  session remains an explicit error, never an implicit switch to another chat.
- Conversation sharing and IDE opening carry an encoded session ID. Local
  native sharing can use the existing paired HTTPS origin; links contain no
  pairing token, caller token or browser credential.
- A fresh device can resume the Gateway's operator-selected conversation.
  Device-local remembered selection remains a preference. Independent windows
  do not forcibly navigate when another client changes its active conversation.
- The Gateway reports the execution host. This is a display label, not a new
  authentication identity, device registry, or claim of provider readiness.
- Existing typed message parts, tool activity, read markers, reactions,
  approvals, request receipts and SSE replay remain Gateway-owned. Drafts and
  native text selection stay local to the viewing device.

## Provider and donor decisions

VS Code supports custom model providers, including Ollama. Ollama Cloud offers
Chat Completions and stateless Responses compatibility; its documentation does
not promise stateful Responses, built-in web search, or freeform tool replay.
Connecting it directly to an extension does not attach that extension to a
Jaeger conversation or give it Jaeger's durable task/approval lifecycle.

Jaeger's OpenAI-compatible adapter is a translation surface, not a replacement
harness. A stable `X-Jaeger-Session-Id` or `user` key reuses a Gateway session.
The adapter does not implement a client-side tool round-trip. For the complete
Jaeger work stream, use the Gateway session/request/event contract.

Reusable upstream candidates are OpenAI's Codex open-source core (Apache-2.0)
and Microsoft's published Copilot Chat source (MIT). The old Copilot Chat
repository is archived and points active development to `microsoft/vscode`.
Reuse must select exact files/revisions, preserve their notices, and account
for third-party components. The proprietary packaged products and their
cloud services are not implied donors. This repair copies no donor code.

Honcho is an optional derived-memory service, useful for long-term entity/user
context. It does not fix wrong conversation selection, replay, ownership, or
approval reconciliation. Keep the local Gateway store authoritative and assess
memory quality separately before adding another service or exporting history.

Sources reviewed 2026-11-08:

- https://learn.chatgpt.com/docs/app-server
- https://github.com/openai/codex/blob/main/LICENSE
- https://github.com/microsoft/vscode-copilot-chat/blob/main/LICENSE.txt
- https://github.com/microsoft/vscode-copilot-chat/blob/main/README.md
- https://code.visualstudio.com/docs/agent-customization/language-models
- https://docs.ollama.com/api/openai-compatibility
- https://honcho.dev/docs/v3/documentation/introduction/overview

## Verification boundaries

`test_cross_client_continuity.py` runs real owned Gateway/runtime processes with
a scripted model boundary. It exercises owner IDE/WebUI/CLI callers, persisted
history, duplicate admission and restart without another execution. UI component
tests cover exact links, stale-device selection, unavailable sessions and browser
history. These checks do not establish physical phone rendering or full Codex /
Copilot parity. Live qualification must additionally exercise the installed
public WebUI, configured provider and persisted same-session follow-up.
