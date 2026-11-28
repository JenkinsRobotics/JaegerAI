# Jaeger verification quick reference

Sources: `AGENTS.md` and `scripts/verify.sh` (repo root). Line numbers cited inline.

## Verification commands

The dispatcher is `scripts/verify.sh`, which takes one optional target argument
(`TARGET="${1:-all}"`, `scripts/verify.sh:11`) and dispatches via its `case`
block (`scripts/verify.sh:53-57`):

- **Backend-only:** `./scripts/verify.sh backend`
  Runs `run_backend` (`scripts/verify.sh:54` → `scripts/verify.sh:13-44`): pytest over the
  27 standalone `packages/jaeger-*/tests` directories plus `dev/tests`
  (`scripts/verify.sh:15-43`).
- **Frontend-only:** `./scripts/verify.sh frontend`
  Runs `run_frontend` (`scripts/verify.sh:55` → `scripts/verify.sh:46-51`): `npm run test`
  in `jaeger_ai/interfaces/ui`, then the external build via
  `jaeger_ai/interfaces/ui/scripts/build-external.py` (`scripts/verify.sh:48-50`).
- **Full (backend + frontend + build):** `./scripts/verify.sh` (or `./scripts/verify.sh all`),
  also exposed as `./jaeger verify` (`AGENTS.md:24`, `scripts/verify.sh:56`).

## Where the built WebUI is kept

UI production builds live **outside the repo** at
`~/.cache/jaeger/ui-rebuild-mainscreen/dist` (`AGENTS.md:7`, Golden Rule 1:
"Zero in-repo runtime junk"). The same rule keeps the virtualenv at
`~/.jaeger/venv` (override via `JAEGER_VENV`) and Python bytecode outside the
repo (`PYTHONDONTWRITEBYTECODE=1`) (`AGENTS.md:7`).

## Why the script disables pytest's cache provider

`run_backend` invokes pytest with `-p no:cacheprovider`
(`scripts/verify.sh:15`). Verified observation: the flag is present on the
pytest command line; the script itself does not print a reason. The grounded
explanation (inference from `AGENTS.md:7`, Golden Rule 1 "Zero in-repo runtime
junk"): pytest's cache provider writes a `.pytest_cache/` directory into the
repo root on every run, which would violate the zero in-repo runtime junk
rule. The script enforces the same hygiene for bytecode by exporting
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"`
(`scripts/verify.sh:5-6`), so `-p no:cacheprovider` is the cache-directory
counterpart of those two exports.
