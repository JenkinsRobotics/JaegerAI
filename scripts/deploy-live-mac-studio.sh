#!/usr/bin/env bash
# Publish the exact pushed master commit to the operator's Mac Studio.
#
# This is deliberately fail-closed: a dirty tree, non-master checkout,
# unpushed commit, failed build, stale service, or served-byte mismatch makes
# the deployment fail. If cutover has started, the previous source and UI are
# restored before the command returns an error.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${JAEGER_LIVE_HOST:-mac-studio}"
PUBLIC_URL="${JAEGER_LIVE_URL:-https://matthews-mac-studio.tail80f206.ts.net:8443/}"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy-live-mac-studio.sh [--host SSH_HOST] [--url HTTPS_URL]

Deploys the current, clean, pushed master commit to ~/.jaeger/source on the
Mac Studio, rebuilds the canonical UI, atomically replaces the served bundle,
restarts Gateway/agent/Web UI/MCP, and verifies commit plus served bytes.

Environment equivalents:
  JAEGER_LIVE_HOST   SSH host (default: mac-studio)
  JAEGER_LIVE_URL    public HTTPS URL
EOF
}

while (($#)); do
  case "$1" in
    --host)
      HOST="${2:?--host needs a value}"
      shift 2
      ;;
    --url)
      PUBLIC_URL="${2:?--url needs a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${REPO_ROOT}"

if [[ "$(git branch --show-current)" != "master" ]]; then
  echo "[deploy-live] Refusing deployment outside master." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "[deploy-live] Refusing deployment from a dirty working tree." >&2
  git status --short >&2
  exit 1
fi

echo "[deploy-live] Fetching the published master ref..."
git fetch --quiet origin master
LOCAL_COMMIT="$(git rev-parse HEAD)"
PUBLISHED_COMMIT="$(git rev-parse origin/master)"
if [[ "${LOCAL_COMMIT}" != "${PUBLISHED_COMMIT}" ]]; then
  echo "[deploy-live] Refusing an unpushed or out-of-date commit." >&2
  echo "  local:  ${LOCAL_COMMIT}" >&2
  echo "  origin: ${PUBLISHED_COMMIT}" >&2
  exit 1
fi

echo "[deploy-live] Deploying ${LOCAL_COMMIT} to ${HOST}..."
ssh "${HOST}" bash -s -- "${LOCAL_COMMIT}" "${PUBLIC_URL}" <<'REMOTE'
set -Eeuo pipefail

EXPECTED_COMMIT="$1"
PUBLIC_URL="$2"
REPO_ROOT="${HOME}/.jaeger/source"
UI_ROOT="${REPO_ROOT}/jaeger_ai/interfaces/ui"
SERVED_PARENT="${HOME}/.cache/jaeger/ui-rebuild-mainscreen"
SERVED_DIST="${SERVED_PARENT}/dist"
RELEASE_ROOT="${HOME}/.cache/jaeger/ui-releases"
STATUS_FILE="$(mktemp -t jaeger-live-status.XXXXXX)"
HEALTH_FILE="$(mktemp -t jaeger-live-health.XXXXXX)"
PUBLIC_INDEX="$(mktemp -t jaeger-live-index.XXXXXX)"
OLD_COMMIT=""
BACKUP_DIR=""
CUTOVER_STARTED=0

cleanup() {
  rm -f "${STATUS_FILE}" "${HEALTH_FILE}" "${PUBLIC_INDEX}"
}

rollback() {
  local code=$?
  trap - ERR
  if ((code != 0 && CUTOVER_STARTED == 1)); then
    echo "[deploy-live] Verification failed; restoring ${OLD_COMMIT}." >&2
    set +e
    cd "${REPO_ROOT}"
    ./jaeger stack down --json >&2
    git reset --hard "${OLD_COMMIT}" >&2
    if [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]]; then
      rm -rf "${SERVED_DIST}.rollback-next"
      cp -a "${BACKUP_DIR}" "${SERVED_DIST}.rollback-next"
      rm -rf "${SERVED_DIST}"
      mv "${SERVED_DIST}.rollback-next" "${SERVED_DIST}"
    fi
    cd "${UI_ROOT}"
    npm ci >&2
    cd "${REPO_ROOT}"
    ./jaeger stack up gateway agent webui mcp --json >&2
    set -e
  fi
  cleanup
  exit "${code}"
}
trap rollback ERR
trap cleanup EXIT

cd "${REPO_ROOT}"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "[deploy-live] Remote source is dirty; refusing to erase it." >&2
  git status --short >&2
  exit 1
fi
OLD_COMMIT="$(git rev-parse HEAD)"

git fetch --quiet origin master
if [[ "$(git rev-parse origin/master)" != "${EXPECTED_COMMIT}" ]]; then
  echo "[deploy-live] Remote origin/master does not match the requested commit." >&2
  exit 1
fi
git reset --hard "${EXPECTED_COMMIT}"

echo "[deploy-live] Reinstalling UI dependencies and building production assets..."
cd "${UI_ROOT}"
npm ci
npm run build
SOURCE_HASH="$(shasum -a 256 dist/index.html | awk '{print $1}')"

mkdir -p "${SERVED_PARENT}" "${RELEASE_ROOT}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${RELEASE_ROOT}/${OLD_COMMIT:0:8}-before-${EXPECTED_COMMIT:0:8}-${STAMP}"
if [[ -d "${SERVED_DIST}" ]]; then
  cp -a "${SERVED_DIST}" "${BACKUP_DIR}"
fi

cd "${REPO_ROOT}"
./jaeger stack down --json
CUTOVER_STARTED=1

NEXT_DIST="${SERVED_PARENT}/dist.next.$$"
OLD_DIST="${SERVED_PARENT}/dist.old.$$"
rm -rf "${NEXT_DIST}" "${OLD_DIST}"
cp -a "${UI_ROOT}/dist" "${NEXT_DIST}"
if [[ -d "${SERVED_DIST}" ]]; then
  mv "${SERVED_DIST}" "${OLD_DIST}"
fi
mv "${NEXT_DIST}" "${SERVED_DIST}"
rm -rf "${OLD_DIST}"

./jaeger stack up gateway agent webui mcp --json
./jaeger stack status --json >"${STATUS_FILE}"
curl -fsS http://127.0.0.1:33418/health >"${HEALTH_FILE}"
curl -fsS "${PUBLIC_URL}" >"${PUBLIC_INDEX}"

python3 - "${STATUS_FILE}" "${HEALTH_FILE}" "${EXPECTED_COMMIT}" <<'PY'
import json
import sys

status_path, health_path, expected = sys.argv[1:]
status = json.load(open(status_path, encoding="utf-8"))
health = json.load(open(health_path, encoding="utf-8"))
required = {"gateway", "agent", "webui", "mcp"}
services = {row["id"]: row for row in status.get("services", [])}
missing = sorted(required - services.keys())
if missing:
    raise SystemExit(f"missing required services: {missing}")
for service_id in sorted(required):
    row = services[service_id]
    if not row.get("ready") or not row.get("managed") or row.get("stale"):
        raise SystemExit(f"unhealthy service {service_id}: {row}")
    if row.get("git_commit") != expected or row.get("head_commit") != expected:
        raise SystemExit(f"wrong commit for {service_id}: {row}")
if health.get("commit") != expected:
    raise SystemExit(f"Gateway health commit mismatch: {health.get('commit')} != {expected}")
if not health.get("all_green"):
    raise SystemExit(f"Gateway is not all-green: {health}")
PY

SERVED_HASH="$(shasum -a 256 "${SERVED_DIST}/index.html" | awk '{print $1}')"
PUBLIC_HASH="$(shasum -a 256 "${PUBLIC_INDEX}" | awk '{print $1}')"
if [[ "${SOURCE_HASH}" != "${SERVED_HASH}" || "${SOURCE_HASH}" != "${PUBLIC_HASH}" ]]; then
  echo "[deploy-live] UI byte mismatch." >&2
  echo "  source: ${SOURCE_HASH}" >&2
  echo "  served: ${SERVED_HASH}" >&2
  echo "  public: ${PUBLIC_HASH}" >&2
  exit 1
fi

CUTOVER_STARTED=0
echo "[deploy-live] LIVE ${EXPECTED_COMMIT}"
echo "[deploy-live] UI SHA-256 ${SOURCE_HASH}"
echo "[deploy-live] URL ${PUBLIC_URL}"
REMOTE

echo "[deploy-live] Verified live commit ${LOCAL_COMMIT}."
