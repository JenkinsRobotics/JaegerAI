# Third-party notices

## Kilo Code transcript mechanisms

`media/frame-queue.js`, `media/timeline.js`, and `media/keyed-renderer.js`
selectively adapt the animation-frame queue and stable-key transcript patterns
from **Kilo Code v7.7.9**.

- Repository: https://github.com/Kilo-Org/kilocode
- Release: `v7.7.9`
- Commit: `d52877ea1c0a02284a4a87d2da0082d2f6dbefb7`
- Source: `packages/kilo-vscode/webview-ui/src/context/frame-queue.ts`
- Source: `packages/kilo-vscode/webview-ui/src/context/transcript-rows.ts`
- License: MIT
- Copyright (c) 2026 Kilo Code
- Copyright (c) 2025 opencode

Jaeger's copies are modified into build-free browser/CommonJS modules with
Gateway-specific reduction, DOM reconciliation, tests, and packaging. No Kilo
daemon, provider, SDK, account, session database, SolidJS component, or agent
runtime is included. The MIT text below applies to these files too.

## streaming-markdown

This extension's panel renders assistant replies with **streaming-markdown**,
an incremental Markdown-to-DOM parser built for token-by-token output.

- Package: `streaming-markdown@0.2.15`
- Author: Damian Tarnawski
- Repository: https://github.com/thetarnav/streaming-markdown
- License: MIT (full text below)

The library is not copied into this source tree. `package_extension.py`
copies the SAME file JaegerAI's WebUI already vendors at
`jaeger_ai/features/webui/static/vendor/smd.min.js` (self-hosted from the
pinned npm release, no CDN) into the staged extension at packaging time, so
there is exactly one copy of the file in the repository. If that file is
missing or fails to load, the panel falls back to plain, safely-escaped text
with fenced code blocks — Markdown rendering is an enhancement, never a
requirement for correctness or safety.

```
MIT License

Copyright (c) 2024 Damian Tarnawski

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Not included this pass

KaTeX (math rendering) is vendored in the WebUI but is deliberately **not**
reused here yet: it ships dozens of font files and its packaging/licensing
footprint needs its own review. Chat replies render as Markdown without math
typesetting until that review happens. This is a scoping decision, not a
missing feature hidden from the operator.
