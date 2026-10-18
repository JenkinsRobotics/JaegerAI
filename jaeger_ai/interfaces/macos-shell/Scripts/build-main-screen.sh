#!/bin/zsh
# build-main-screen.sh — builds the new main screen (jaeger_ai/interfaces/ui) for the shell's dev/test stack.
# Output goes OUTSIDE the UI tree (~/.cache/jaeger/ui-rebuild-mainscreen/dist); the UI source tree is only read
# (a snapshot hash is printed before/after to prove it). Uses the UI's own node_modules and vite.config.ts.
set -eu
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
UI="$REPO/jaeger_ai/interfaces/ui"
OUT="$HOME/.cache/jaeger/ui-rebuild-mainscreen/dist"
# --mock: the screenshot build (VITE_JAEGER_MOCK=1 keeps the UI's own mock data), in a separate folder.
if [[ "${1:-}" == "--mock" ]]; then OUT="$HOME/.cache/jaeger/ui-rebuild-mainscreen/dist-mock"; export VITE_JAEGER_MOCK=1; fi
NODE="${JAEGER_SHELL_DEV_NODE:-$(command -v node || echo /opt/homebrew/bin/node)}"
[[ -x "$NODE" ]] || { echo "node not found"; exit 1; }
[[ -f "$UI/node_modules/vite/bin/vite.js" ]] || { echo "UI deps missing in $UI/node_modules (not installed by this script)"; exit 1; }
snap() { (cd "$UI" && find . -path ./node_modules -prune -o -type f -print0 | sort -z | xargs -0 shasum | shasum | cut -c1-12); }
BEFORE=$(snap)
mkdir -p "${OUT:h}"
(cd "$UI" && "$NODE" node_modules/vite/bin/vite.js build --outDir "$OUT" --emptyOutDir --logLevel warn)
AFTER=$(snap)
echo "main screen built: $OUT (ui source snapshot $BEFORE → $AFTER $([[ $BEFORE == $AFTER ]] && echo unchanged || echo CHANGED-DURING-BUILD))"
