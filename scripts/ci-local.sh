#!/usr/bin/env bash
#
# Local CI for JaegerAI: the checks CI would run, runnable on an unpushed
# branch. Nothing is written inside the checkout: pytest runs through
# dev/scripts/run_tests.sh (isolated /tmp state root, caches under ~/.cache),
# and the UI build goes to a temporary directory.
#
# Usage:
#   scripts/ci-local.sh                # python unit tier + UI checks + import smoke
#   scripts/ci-local.sh --full         # python: every tier plus the package suites
#   scripts/ci-local.sh -- <args>      # extra pytest args (root suite only)
#
# Environment:
#   JAEGER_PYTHON   interpreter with pytest installed (default: $JAEGER_VENV/bin/python,
#                   else ~/.jaeger/venv/bin/python, else python3)
#
# Exit status: 0 only when every step passes. Skipped steps are listed in the
# summary and do not fail the run.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

TIER="--unit"
PYTEST_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --full) TIER="--full" ;;
        --unit) TIER="--unit" ;;
        --) shift; PYTEST_ARGS=("$@"); break ;;
        -h|--help) sed -n '3,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "[ci-local] unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -n "${JAEGER_PYTHON:-}" ]; then
    PY="$JAEGER_PYTHON"
elif [ -n "${JAEGER_VENV:-}" ] && [ -x "${JAEGER_VENV}/bin/python" ]; then
    PY="${JAEGER_VENV}/bin/python"
elif [ -x "${HOME}/.jaeger/venv/bin/python" ]; then
    PY="${HOME}/.jaeger/venv/bin/python"
else
    PY="$(command -v python3)"
fi

WORK="$(mktemp -d /tmp/jaeger-ci-local.XXXXXXXX)"
trap 'rm -rf "$WORK"' EXIT

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
export JAEGER_TEST_HEADLESS=1
export JAEGER_NO_ATTACH=1

NAMES=()
RESULTS=()
record() { NAMES+=("$1"); RESULTS+=("$2"); }

step() {
    local name="$1"; shift
    local log="$WORK/$(echo "$name" | tr -c 'A-Za-z0-9' '_').log"
    printf '\n[ci-local] ==> %s\n' "$name"
    if "$@" 2>&1 | tee "$log"; then
        record "$name" PASS
    else
        record "$name" FAIL
        printf '[ci-local] FAILED: %s (log tail above)\n' "$name"
    fi
}

# 1. Python tests, through the documented runner so env hygiene and isolation
#    stay defined in one place. run_tests.sh runs "$JAEGER_VENV/bin/pytest";
#    point it at a shim that runs pytest under the chosen interpreter.
python_tests() {
    mkdir -p "$WORK/venv-shim/bin"
    printf '#!/usr/bin/env bash\nexec %q -m pytest "$@"\n' "$PY" > "$WORK/venv-shim/bin/pytest"
    chmod +x "$WORK/venv-shim/bin/pytest"
    "$PY" -c 'import pytest' || { echo "[ci-local] $PY has no pytest"; return 1; }
    JAEGER_VENV="$WORK/venv-shim" dev/scripts/run_tests.sh "$TIER" -- \
        ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}
}

# 2. UI: theme guard, typecheck, production build into $WORK. Never installs
#    dependencies (that would rewrite node_modules and the lockfile).
UI_DIR="jaeger_ai/interfaces/ui"
ui_checks() {
    cd "$REPO/$UI_DIR"
    if [ ! -d node_modules ]; then
        echo "[ci-local] $UI_DIR/node_modules is missing; run 'npm ci' there first"
        return 1
    fi
    # Explicit `|| return 1`: set -e is suspended inside a function that runs
    # as an `if` condition, so a failing check would otherwise be ignored.
    echo "[ci-local] theme guard"; node scripts/check-theme-literals.mjs || return 1
    echo "[ci-local] typecheck"; node_modules/.bin/tsc --noEmit -p tsconfig.json || return 1
    echo "[ci-local] build"
    node_modules/.bin/vite build --configLoader runner --outDir "$WORK/ui-dist" --emptyOutDir --logLevel warn || return 1
    test -f "$WORK/ui-dist/index.html" || { echo "[ci-local] build produced no index.html"; return 1; }
    echo "[ci-local] UI build OK ($(du -sk "$WORK/ui-dist" | cut -f1) KB, written to a temp dir)"
}

# 3. Import smoke: the CLI entry point and the gateway import cleanly and the
#    port contract is loopback. Nothing is started or bound.
import_smoke() {
    PYTHONPATH="$REPO/packages/jaeger-agent:$REPO/packages/jaeger-os:$REPO${PYTHONPATH:+:$PYTHONPATH}" \
    JAEGER_HOME="$WORK/state" "$PY" - <<'PY'
import importlib
from pathlib import Path
import sys

repo = Path.cwd().resolve()
entry = importlib.import_module("jaeger_ai.cli.entry")
assert callable(getattr(entry, "main", None)), "jaeger_ai.cli.entry.main is not callable"
server = importlib.import_module("jaeger_ai.core.gateway.server")
assert hasattr(server, "JaegerGatewayApp") and callable(server.main), "gateway server entry missing"
importlib.import_module("jaeger_ai.core.gateway.openai_compat")
ports = importlib.import_module("jaeger_ai.contract.ports")
assert ports.LOOPBACK == "127.0.0.1", ports.LOOPBACK
assert ports.GATEWAY_URL.startswith("http://127.0.0.1:"), ports.GATEWAY_URL
for mod in (entry, server, ports):
    src = Path(mod.__file__).resolve()
    assert repo in src.parents, f"{mod.__name__} imported from {src}, not this checkout"
print(f"imports OK from {repo}; gateway {ports.GATEWAY_URL}; python {sys.version.split()[0]}")
PY
}

echo "[ci-local] repo $REPO @ $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "[ci-local] python $PY"
step "import smoke (cli.entry, gateway)" import_smoke
if [ -d "$UI_DIR" ]; then
    if command -v node >/dev/null 2>&1; then
        step "ui: theme guard + typecheck + build" ui_checks
    else
        echo "[ci-local] node not found"; record "ui: theme guard + typecheck + build" FAIL
    fi
else
    record "ui: theme guard + typecheck + build" "SKIP ($UI_DIR absent)"
fi
step "python tests ($TIER)" python_tests

echo
echo "[ci-local] ===== summary ====="
STATUS=0
for i in "${!NAMES[@]}"; do
    printf '  %-24s %s\n' "${RESULTS[$i]}" "${NAMES[$i]}"
    [ "${RESULTS[$i]}" = FAIL ] && STATUS=1
done
if [ "$STATUS" -eq 0 ]; then echo "[ci-local] RESULT: PASS"; else echo "[ci-local] RESULT: FAIL"; fi
exit "$STATUS"
