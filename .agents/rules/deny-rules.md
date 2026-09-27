# Operational Safety & Deny Rules for Agents

## 1. Process Management & Termination Guard
* **NEVER run `pkill -f` or `killall`:**
  * Blanket process killing risks abruptly killing active Gateway daemons (`jaeger gateway daemon`), IDE extension servers, or user workspace processes.
  * To stop or restart services, use explicit lifecycle verbs (e.g., `jaeger gateway stop`, `jaeger bridge stop`) or query the specific process PID (`lsof -i :8810`) and terminate only that PID.

## 2. Git Staging & Index Safety
* **NEVER run blanket staging commands:**
  * `git add .`, `git add -A`, or `git commit -a` are strictly forbidden.
  * Always stage explicit, targeted paths (e.g. `git add jaeger_ai/features/webui/api/oauth.py`).
  * Blanket staging risks accidentally committing untracked build caches, temporary scratch files, or sensitive configuration files.

## 3. Zero In-Repo State & No Compat Shims
* **NEVER create files outside the Root Allowlist:**
  * Files in the repository root are strictly governed by `ALLOWED_ROOT_ITEMS` enforced in `dev/tests/jaeger_ai/core/test_ci_hygiene.py`.
  * Temporary scripts and debugging scratchpads belong strictly in external scratch directories, never in `<repo>/`.
* **NEVER add compatibility shims:**
  * When code moves or is deleted, update all importing sites directly.
  * Never introduce forwarding modules (e.g., `hermes_state.py`) or re-exports in the root or feature directories.

## 4. Single-Command Verification
* Before concluding any turn or declaring a task complete, run:
  ```bash
  ./scripts/verify.sh
  ```
  All 4 verification stages (Git invariants, CI hygiene tripwires, IDE unit tests, Core Gateway & Catalog tests) must pass.
