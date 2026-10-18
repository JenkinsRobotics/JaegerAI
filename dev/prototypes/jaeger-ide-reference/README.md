# Jaeger IDE webview reference

This preview serves the actual Jaeger IDE `media/index.html`, CSS, and
JavaScript from `jaeger_ai/interfaces/ide/media/`. The extension view and its
client-side interactions are therefore the same code used by the IDE. Only the
VS Code API and Gateway boundary is simulated by `harness.js` with sample data.

Start it from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 dev/prototypes/jaeger-ide-reference/server.py
```

Then open `http://127.0.0.1:18731`. The server binds only to loopback. Sending a
message produces a canned preview response; it never contacts Jaeger, accesses
workspace files, or calls an AI model. Some host actions display a local demo
card because the VS Code extension host is not present.
