#!/usr/bin/env bash
# Shared external output resolver; never creates a directory.
set -euo pipefail
REPO="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$HOME/.cache/jaeger/pycache" PYTHONPATH="$REPO" python3 -B - "$REPO" <<'PY'
from pathlib import Path
from jaeger_ai.cli._common import mac_shell_build_dir
import sys
print(mac_shell_build_dir(Path(sys.argv[1])))
PY
