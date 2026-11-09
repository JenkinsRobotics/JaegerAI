# Jaeger browser runtime

Owns the packaged browser dependencies, not conversations or agent execution.
Steel Browser is an Apache-2.0 dependency pinned at
`c8aebf9462187fc5a80b587ba2086900aecab236`. Its source and license remain in
the produced bundle. Three bounded integration patches supply per-conversation storage, authenticate
the internal cast connection, and guard startup on a real browser instance.
The worker adapter also normalizes the upstream cast session URL.
Node 22.23.2 is verified against its pinned SHA-256.
Chromium is pinned by the canonical UI's Playwright lockfile. No developer
Node, Homebrew, system Chrome, Docker or separately started service is needed
to run the resulting bundle.

Build on macOS arm64 after installing the canonical UI's locked dependencies:

```
python3 packages/jaeger-browser/build.py --output /tmp/jaeger-browser-candidate
```

Install the complete directory at `<operator_state_root>/runtimes/browser`,
or set `JAEGER_BROWSER_BUNDLE` to its path. This is release-owned content;
profiles and logs are stored separately under `<operator_state_root>/browser`.
The Gateway starts a private worker only when a conversation opens its browser.
Its stdin lifetime lease shuts down Chromium if the Gateway exits.

The adapter exposes navigation, snapshots, element actions and a streamed
interactive viewer. It does not embed destination sites as iframes. The WebUI
and native WKWebView display the same Gateway-owned browser. Steel's raw CDP
and administrative endpoints are never proxied to clients.
