# @jaeger/design-tokens
Single source: `tokens/jaeger-tokens.json`. Never edit `dist/` by hand.
- `npm run build` regenerates `dist/` (jaeger.css, jaeger-vscode-map.css, aether.css, JaegerTokens.swift, theme.py, contrast-report.json) and `dist/MANIFEST.json` (sha256 pins).
- `npm run verify` fails if `dist/` differs from a fresh build by even one byte.
