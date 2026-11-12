# Third-party notices — Jaeger UI

The live Process view (`src/process/`) is built on these open-source packages,
installed from npm and bundled into `dist/` at build time. Their license texts
ship inside each package under `node_modules/<name>/LICENSE`.

| Package | Version | License | Upstream | Used for |
|---|---|---|---|---|
| `@xyflow/react` (React Flow) | 12.x | MIT, © webkid GmbH | https://github.com/xyflow/xyflow | Node canvas: pan/zoom, handles, edges, minimap, controls |
| `@dagrejs/dagre` | 3.x | MIT, © Chris Pettitt | https://github.com/dagrejs/dagre | Left-to-right automatic graph layout |
| `lucide-react` | 1.x | ISC, © Lucide Contributors (portions MIT, © Cole Bemis — Feather) | https://github.com/lucide-icons/lucide | Node, status and toolbar icons |
| `motion` | 14.x | MIT, © Motion Division Ltd | https://github.com/motiondivision/motion | Spinner and state-change animation (honours reduced motion) |

## Design references (no code used)

The Process view's visual pattern — node cards with an icon tile, title and
subtitle, status marks, circular handles, animated edges, an inspector panel,
and a trace waterfall — was informed by n8n's editor canvas and by
Langfuse/Honeycomb trace waterfalls. **No n8n source code is copied or
included**: n8n is distributed under the Sustainable Use License, so Jaeger
only emulates the general interaction pattern, implemented from scratch on
React Flow and styled with Jaeger's own `--jg-*` design tokens.
