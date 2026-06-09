"""After-action reflection.

Both Hermes ("skills self-improve during use") and ARES ("retrospective
learning after every task") close a learning loop: when a task
finishes, the agent reflects on it and the lesson persists. Jaeger had
memory but no reflection step — this module is that step.

After a Deep Think task completes, a bounded LLM call asks: what
worked, what was hard, what reusable pattern or user preference is
worth remembering. The reflection is:

  • appended to ``<instance>/memory/reflections.jsonl`` (chronological)
  • written into episodic memory, so ``search_memory`` surfaces it
    later — the agent rediscovers its own lessons naturally

Import-clean: takes a ``client`` so there's no dependency on
jaeger_os.main.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


_REFLECT_DIRECTIVE = (
    "You just finished a task. Reflect on it briefly — this reflection "
    "is saved to memory so a future version of you can learn from it.\n\n"
    "Task: {task}\n"
    "Outcome: {outcome}\n\n"
    "In 2-3 short sentences, cover:\n"
    "  • What worked / what approach succeeded.\n"
    "  • What was hard or failed, and why.\n"
    "  • Any reusable pattern or user preference worth remembering.\n"
    "Plain text. No preamble. If there's genuinely nothing useful to "
    "note, reply with just: (nothing notable)."
)


def reflect_on_task(
    client: Any,
    task: str,
    outcome: str,
    *,
    transcript_tail: str = "",
) -> str:
    """Run the bounded reflection LLM call. Returns the reflection text,
    or "" on any failure (reflection is best-effort — never block the
    work loop on it)."""
    directive = _REFLECT_DIRECTIVE.format(task=task, outcome=outcome)
    messages = [
        {"role": "system",
         "content": "You are reflecting on completed work to extract a "
                    "durable lesson. Be concrete and brief."},
    ]
    if transcript_tail.strip():
        messages.append({
            "role": "user",
            "content": f"What happened (transcript tail):\n{transcript_tail[-3000:]}",
        })
    messages.append({"role": "user", "content": directive})
    try:
        result = client.chat(
            messages,
            max_tokens=180,
            temperature=0.3,
            top_p=0.9,
            stream=False,
        )
        return (getattr(result, "text", None) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def save_reflection(
    layout: Any,
    task: str,
    outcome: str,
    reflection: str,
) -> None:
    """Persist a reflection two ways: a chronological JSONL record, and
    an episodic-memory entry so ``search_memory`` can surface it later.

    Best-effort — a failure to persist a reflection must not break the
    caller's work loop."""
    text = (reflection or "").strip()
    if not text or text.lower() == "(nothing notable)":
        return

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": task,
        "outcome": outcome,
        "reflection": text,
    }

    # 1. Chronological record.
    try:
        path: Path = layout.memory_dir / "reflections.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass

    # 2. Episodic memory — so search_memory rediscovers the lesson.
    try:
        from jaeger_os.core.memory import memory as mem
        mem.append_episodic({
            "timestamp": entry["timestamp"],
            "framework": "jaeger_os",
            "session_key": "reflection",
            "user": f"[reflection on: {task}]",
            "answer": text,
        })
    except Exception:  # noqa: BLE001
        pass


def recent_reflections(layout: Any, n: int = 10) -> list[dict[str, Any]]:
    """Return the most recent reflections, newest last."""
    path: Path = layout.memory_dir / "reflections.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows[-max(1, n):]
