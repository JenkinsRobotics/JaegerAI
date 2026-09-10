# Clean Repository & Zero In-Repo State Doctrine

## Mandatory Rules for All Agents Working on JaegerAI

1. **NEVER generate runtime state, logs, or databases in the repository tree:**
   - All runtime databases, instances, session transcripts, and logs MUST go to `~/.jaeger/` (or `$JAEGER_STATE_DIR`).
   - Never write to `<repo>/.jaeger_ai` or `<repo>/.jaeger_agent`.
   - Any runtime code must use `operator_state_root()` from `jaeger_ai.core.instance.instance`.

2. **NEVER build virtualenvs or caches in the repository root:**
   - The Python virtual environment is located at `~/.jaeger/venv`. Never create `.venv` in the repo root.
   - Bytecode generation is disabled (`PYTHONDONTWRITEBYTECODE=1`) or externalized (`PYTHONPYCACHEPREFIX=~/.cache/jaeger/pycache`).
   - Pytest cache is externalized to `~/.cache/pytest`. Never create `__pycache__` or `.pytest_cache` in the repo.

3. **NEVER apply cosmetic workarounds or band-aids:**
   - Do NOT create `.vscode/settings.json` or `.gitignore` rules to mask files that the code is generating.
   - Always trace to the architectural producer and eliminate the in-repo write directly in source code.

4. **Continuous CI Verification:**
   - All changes must pass `dev/tests/jaeger_ai/core/test_ci_hygiene.py` and `dev/scripts/run_tests.sh --smoke`.
