# Continue Jaeger between the WebUI and Mac

Start the stack with `./jaeger start`. In Hermes WebUI, select **Jaeger** and open
**Dispatcher**. Open the Mac chat window and use **Dispatcher** there too. Both
read the same saved conversation and observe the same native run. You can close
one interface and continue in the other; closing a client does not cancel work.

For a direct Mac chat launch when the app is closed:

```sh
open /Applications/JaegerAI.app --args --chat
```

Use the app's menu-bar chat button when it is already running. The current
container address is shown by `./jaeger status`; the app's existing WebUI opener
uses discovery. Do not save a container IP as permanent configuration.

**New Chat** in the Mac app remains a separate native conversation. A new
conversation in the Jaeger WebUI profile remains a Focus thread. Neither is
merged into the Dispatcher. Existing history is preserved. The
Dispatcher button returns to the shared conversation. Recent native Focus
reports are available from **Focus reports** in either Dispatcher view.

Approvals and Stop act on the shared run ID. A Stop request remains pending until
the native worker confirms cancellation. If the observer restarted while work
was active, **Check status** reconciles the original execution; it does not run
the prompt again. Connection failures retain existing history and show an error.
After an unconfirmed send, check the recovered history before sending different
work. Retrying the same uncertain desktop request reuses its request identity.

The native service admits one Dispatcher run at a time. This release does not
provide multiple simultaneous Dispatcher workers. Hermes, OpenClaw and Roundtable
retain their existing profiles and execution paths. Native skills/memory panels
still use their separate extension consent settings; chat continuation does not
change those permissions.

## Ownership and deployment

- `jaeger_ai/core/sessions.py` owns the durable transcript and stable message IDs.
- The existing bridge exposes read-only transcript/connection queries.
- `hermes_profile_adapters/conversation.py` exposes the shared chat/control view
  over the existing Runs service, with durable request deduplication.
- `integrations/hermes_webui/conversation.patch` and `jaeger_conversation.py`
  project native history only for the bound Jaeger Dispatcher. Upstream profile
  authentication and CSRF checks still precede the new routes.
- `DispatcherClient.swift` and the Mac chat view model consume that same service.
- The donor `vendor/hermes-webui` checkout is unchanged. Build patches using
  `scripts/prepare-hermes-webui.py`; the managed deployment image is
  `hermes-webui:jaeger-continuity-20260909`.

## Repeatable live verification

The following check uses the real browser composer and production Swift chat
view model. It adds clearly labeled verification exchanges and consumes model
tokens. It captures no screenshots and grants no tool permissions.

```sh
.venv/bin/python scripts/verify-dispatcher-continuity.py --url http://CURRENT-WEBUI-IP:8787
```

A separate explicit test restarts the **idle** Jaeger bridge and adapter to verify
reconnection and unchanged transcript IDs. Do not run it while real work is active.

```sh
JAEGER_CONTINUITY_RESTART=1 swift test --package-path jaeger_ai/interfaces/swift \
  --filter DispatcherLiveTests/testLiveReconnectAfterBackendRestart
```

Normal `swift test` skips those live tests unless explicitly enabled.
