---
name: jaeger-webui
description: 'Diagnose and verify the Jaeger chat WebUI: frozen Safari, chat 500,
  connection refused, different version, hard refresh/reset banner. Load this for
  ''web UI is down / frozen / wrong version / asking for a hard reset''.'
metadata:
  jros:
    tags:
    - webui
    - jaeger
    - health
    - launchd
    - identity
    category: devops
    related_skills:
    - process-monitoring
    - web-app-qa
    version: 1.1.0
    platforms:
    - macos
    - linux
    requires-tools:
    - terminal
    - browser
    - read_file
    optional-tools:
    - library_search
    - memory
    - recall
---

# JAEGER WEBUI — IDENTITY, NOT JUST HTTP 200

Process-up (listen / 200 / launchd loaded) is not product-up. The user-facing
chat UI is broken until identity matches and a snapshot shows a usable composer
with no recovery banner.

## WHEN TO USE
Web UI frozen, chat 500 / connection refused, "different version", hard
refresh/reset banner, Safari hung, "did you actually fix the web UI?"

## TOOLS
```
read_file("references/stack.md")                 durable port + identity facts
terminal(command="jaeger webui url")             Tailscale chat URL (not loopback)
terminal(command="curl …")                       probe that URL + 8791 /health
browser(action="open", url="<jaeger webui url>")
browser(action="snapshot")                       prove the live Tailscale page
memory(action="recall", key="webui_chat_url")    if library/memory are loaded
library_search(query="jaeger webui identity")    indexed stack digest
```
QA ALWAYS uses the agent's `browser` (+ `terminal` curl probes). Never GUI
automation (`computer_do` / `computer_use`) and never `open_on_host` — those
are the wrong engine for page QA and EXTERNAL_EFFECT-tier besides.

## SOP

1. LOAD FACTS. `read_file("references/stack.md")` (or `library_search` /
   `recall`) — do not reconstruct the port map from chat memory.
2. PROBE IDENTITY on the Tailscale chat URL (`jaeger webui url` /
   `recall webui_chat_url`), not `127.0.0.1`:
   - `GET <chat-url>/` → title must be Jaeger
   - HTML `__HERMES_WEBUI_BUNDLE_VERSION__` must equal
     `/api/settings` `webui_version` (decodeURI, exact string)
   - `GET http://127.0.0.1:8791/health` → JSON `ok: true`
3. If bundle ≠ settings.webui_version: the UI is STILL BROKEN. That is the
   stale-client banner. Do not call it cosmetic. Do not "tell the user to
   hard refresh" as the fix — fix the stamp so they match, restart
   `com.jenkinsrobotics.jaeger-webui`, re-probe.
4. SNAPSHOT with `browser` on the Tailscale chat URL. A visible
   "different version" / "hard refresh" / "hard reset" banner is a
   Critical fail. Loopback and Tailscale are different origins.
5. `jaeger webui status` pid=None can still be running via launchd. Check
   the port / `launchctl list`. 8787 is not the chat bookmark.
6. Reset `com.jenkinsrobotics.jaeger-gateway` if
   `launchctl print gui/$UID/com.jenkinsrobotics.jaeger-gateway` is missing
   even while `:8810` listens (orphan). Kill the listener, bootstrap the
   plist, then reload the Tailscale Safari tab until the Agents list is
   back (not "Gateway agents unavailable").

## ERROR HATCH
- A call failing on a PRECONDITION — PermissionDenied at the confirmation
  gate, "not configured: no HASS_TOKEN" — is NON-RETRYABLE: the environment
  lacks it, so re-emitting the identical call cannot succeed. Diagnose once,
  then switch to the designated path (browser + curl probes).
- `/api/updates/check` `current_version` (release tag) MAY differ from
  git-describe. That is not identity skew and not a reason to ignore a
  hard-refresh banner.
- Identity still skewed after restart → the HTML stamp has a suffix the
  settings API does not. Strip the suffix from
  `__HERMES_WEBUI_BUNDLE_VERSION__` only; keep `?v=` cache-bust on assets.
- Chat 500 with WebUI 200 → probe 8791. Both launchd jobs must be loaded.

## DONE WHEN
Identity matches (bundle == settings.webui_version, title Jaeger), adapter
health is ok, and a `browser` snapshot of the Tailscale chat URL shows the
composer with no version-skew banner. Tell the user that Tailscale URL,
never 127.0.0.1. Only then say it is fixed.