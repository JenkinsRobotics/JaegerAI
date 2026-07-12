"""Opt-in background chain-of-thought SIDECAR (the ``--think`` flag).

NOT to be confused with its neighbour ``deep_think.py``: that is the
autonomous skill-development mode (model swap + kanban-backed job queue).
THIS module is a lightweight per-turn sidecar — when ``--think`` is set,
after each main turn the user's question is ALSO dispatched to a separate
chain-of-thought LLM call on a background thread, purely for logging /
introspection. It changes nothing about the main turn's answer.

The result is appended to ``<instance>/logs/thinking.jsonl`` (the caller
in ``main.py`` passes that per-instance ``log_path``; the module-level
``LOG_PATH`` is only a fallback for direct, instance-less construction).

Why a background thread vs. inline:
- The main path returns immediately, so user-perceived latency is unchanged.
- The thinking call still uses the same llama.cpp model instance — we serialize
  with a lock so we never invoke the model concurrently (llama-cpp-python is
  not thread-safe for that).
- If the user submits the next prompt before thinking finishes, that prompt
  has to wait for the current thinking call to complete.

This is opt-in. Default agent paths pay zero cost.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "thinking.jsonl"


# The "think step by step" instruction is delivered as a USER turn rather
# than a separate system prompt, so the system-prompt prefix in the KV cache
# is shared with decide/finalize. Same lesson as the earlier finalize
# cache-clobber fix.
THINKING_USER_DIRECTIVE = """Don't answer the user's last message normally. Instead, briefly think through it step by step:
1. What the user wants accomplished
2. What information or decisions are required
3. Possible approaches and their tradeoffs
4. A recommended plan in 3-5 concrete steps

No tool calls in this response — analysis only. Keep it under 200 words.
"""


class ThinkingRunner:
    """One per process. Submits thinking jobs to a single-worker pool that
    serializes against a shared LLM lock.

    base_system_prompt is the framework's current main system prompt. Reusing
    it here keeps the KV cache prefix shared with decide/finalize, so a
    thinking call no longer warms-up a separate prefix that would clobber
    the cache for the next decision.
    """

    def __init__(
        self,
        client: Any,
        framework: str,
        llm_lock: threading.Lock,
        base_system_prompt: str,
        log_path: Path | None = None,
    ) -> None:
        self.client = client
        self.framework = framework
        self.llm_lock = llm_lock
        self.base_system_prompt = base_system_prompt
        # When the caller supplies log_path, write per-instance under
        # <instance>/logs/thinking.jsonl. Otherwise fall back to the
        # module-local LOG_PATH so non-instance callers still work.
        self.log_path = log_path or LOG_PATH
        # max_workers=1 so we never queue multiple think jobs against the model.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thinking")
        self._pending = 0
        self._pending_lock = threading.Lock()

    def queue(self, user_text: str, run_id: str | None = None) -> None:
        with self._pending_lock:
            self._pending += 1
        self.executor.submit(self._run, user_text, run_id)

    def _run(self, user_text: str, run_id: str | None) -> None:
        try:
            self._do_run(user_text, run_id)
        except Exception as exc:
            self._log_entry(
                user_text=user_text,
                run_id=run_id,
                thinking="",
                elapsed_s=0.0,
                error=str(exc),
            )
        finally:
            with self._pending_lock:
                self._pending -= 1

    def _do_run(self, user_text: str, run_id: str | None) -> None:
        started = time.perf_counter()
        with self.llm_lock:
            result = self.client.chat(
                [
                    # Same system prompt as decide/finalize — cache-friendly.
                    {"role": "system", "content": self.base_system_prompt},
                    {"role": "user", "content": user_text},
                    # Override the routing behavior for this turn only.
                    {"role": "user", "content": THINKING_USER_DIRECTIVE},
                ],
                max_tokens=512,
                temperature=0.7,
                top_p=0.95,
                stream=False,
            )
        elapsed = time.perf_counter() - started
        self._log_entry(
            user_text=user_text,
            run_id=run_id,
            thinking=result.text,
            elapsed_s=elapsed,
        )

    def _log_entry(
        self,
        *,
        user_text: str,
        run_id: str | None,
        thinking: str,
        elapsed_s: float,
        error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "framework": self.framework,
            "user": user_text,
            "elapsed_s": round(elapsed_s, 3),
            "thinking": thinking,
        }
        if error:
            entry["error"] = error
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def shutdown(self, wait: bool = True, timeout: float = 60.0) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=not wait)

    def pending(self) -> int:
        with self._pending_lock:
            return self._pending
