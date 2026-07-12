"""Jaeger-local cron runner.

Threading model + atomic-claim semantics match memory/cron_runner.py at
the project root; the only difference is this one talks to
jaeger_os.memory (instance-scoped) instead of the project-root
memory module, so two Jaeger instances on the same host can't double-fire
each other's schedules.

The runner ALSO does daily housekeeping (log rotation): once per UTC day
it calls back into the optional `housekeeping` callable. Housekeeping is
intentionally separate from agent-authored schedules so the human never
needs to schedule it manually.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from jaeger_ai.core.memory import memory as mem


class CronRunner(threading.Thread):
    def __init__(
        self,
        callback: Callable[..., Any],
        *,
        poll_s: float = 30.0,
        llm_lock: threading.Lock | None = None,
        housekeeping: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="jaeger-cron")
        self._callback = callback
        self._poll_s = max(1.0, float(poll_s))
        self._lock = llm_lock
        self._stop_event = threading.Event()
        self._housekeeping = housekeeping
        # Track the UTC day we last ran housekeeping for. None = not yet
        # this process. We set this to today on startup (housekeeping
        # already ran at startup in main.py) so we don't double-run on
        # the first tick.
        self._last_housekeeping_day = datetime.now(timezone.utc).date()

    def shutdown(self, wait: bool = True) -> None:
        self._stop_event.set()
        if wait:
            self.join(timeout=5.0)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                claimed = mem.claim_due_schedules(now=datetime.now(timezone.utc))
            except Exception as exc:
                print(f"[jaeger-cron] claim error: {exc}", flush=True)
                claimed = []
            for sched in claimed:
                if self._stop_event.is_set():
                    break
                name = sched.get("name") or "?"
                prompt = sched.get("prompt") or ""
                if not prompt:
                    continue
                print(f"[jaeger-cron] firing {name!r}: {prompt!r}", flush=True)
                try:
                    if self._lock is not None:
                        with self._lock:
                            self._invoke(prompt, name)
                    else:
                        self._invoke(prompt, name)
                except Exception as exc:
                    print(f"[jaeger-cron] {name!r} callback failed: {exc}", flush=True)

            self._maybe_run_housekeeping()
            self._stop_event.wait(self._poll_s)

    def _invoke(self, prompt: str, schedule_name: str) -> None:
        key = f"cron:{schedule_name}"
        try:
            self._callback(prompt, session_key=key)
        except TypeError:
            self._callback(prompt)

    def _maybe_run_housekeeping(self) -> None:
        """Run the housekeeping callback at most once per UTC day."""
        if self._housekeeping is None:
            return
        today = datetime.now(timezone.utc).date()
        if today == self._last_housekeeping_day:
            return
        self._last_housekeeping_day = today
        try:
            self._housekeeping()
        except Exception as exc:
            print(f"[jaeger-cron] housekeeping failed: {exc}", flush=True)
