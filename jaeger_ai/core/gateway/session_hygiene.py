"""Session hygiene: archive benchmark/probe/test sessions, never delete them.

``classify`` sorts a session row (as ``GET /v1/sessions`` returns it) into
``chat`` (a real conversation: keep), ``system`` (a background producer's own
session: keep), ``agent`` (an agent's home session: keep) or ``junk``. Junk is
archived through the gateway's ``PATCH /v1/sessions/{id}`` (the single writer of
archive state), with a manifest so ``restore`` can undo exactly what was done.

    python -m jaeger_ai.core.gateway.session_hygiene            # dry run
    python -m jaeger_ai.core.gateway.session_hygiene --apply
    python -m jaeger_ai.core.gateway.session_hygiene --restore <manifest.json>
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

SYSTEM_SESSIONS = frozenset({"desktop-app", "jaeger-initiative", "heartbeat", "kanban_idle"})

_JUNK_ID = (
    (re.compile(r"^sota-"), "benchmark run (sota)"),
    (re.compile(r"^noskip-"), "eval probe (noskip)"),
    (re.compile(r"^cap-[a-z0-9]+-[0-9a-f]{6}$"), "capability probe"),
    (re.compile(r"^task:"), "durable-task child session"),
    (re.compile(r"^specialist:"), "specialist child session"),
    (re.compile(r"^jaeger-(computer-use|screenshot|mouse)-live"), "live verification probe"),
    (re.compile(r"^jaeger-(compute|screens)"), "live verification probe"),
    (re.compile(r"^(paste|paste-only|halt|stuck-jaeger|workspace)$"), "named harness session"),
)
_JUNK_TITLE = (
    (re.compile(r"(?i)^stack-verify-probe$"), "stack verification probe"),
    (re.compile(r"(?i)live verification$"), "live verification probe"),
    (re.compile(r"(?i)^local-model-verify$"), "model verification probe"),
    (re.compile(r"(?i)^(test chat|chat test \d*)$"), "test chat"),
    (re.compile(r"(?i)^\[skill-review:"), "skill-review loop"),
    (re.compile(r"(?i)acceptance test|^benchmark "), "benchmark/acceptance run"),
)
_EMPTY_TITLES = frozenset({"new conversation", "new chat", ""})


def classify(row: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, reason). kind is chat | system | agent | junk."""
    sid = str(row.get("session_id") or "")
    title = str(row.get("title") or "").strip()
    meta = row.get("metadata") or {}
    if sid in SYSTEM_SESSIONS:
        return "system", "background producer session"
    if meta.get("home") and meta.get("agent_id"):
        return "agent", f"home session of {meta.get('agent_id')}"
    for rx, why in _JUNK_ID:
        if rx.search(sid):
            return "junk", why
    for rx, why in _JUNK_TITLE:
        if rx.search(title):
            return "junk", why
    if int(row.get("message_count") or 0) == 0 and title.lower() in _EMPTY_TITLES:
        return "junk", "empty conversation"
    return "chat", "conversation"


def plan(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Visible junk sessions to archive (already-archived ones are left alone)."""
    out = []
    for row in rows:
        if (row.get("metadata") or {}).get("archived"):
            continue
        kind, why = classify(row)
        if kind == "junk":
            out.append({"session_id": str(row["session_id"]), "title": str(row.get("title") or ""), "reason": why})
    return out


def apply(items: list[dict[str, str]], patch: Callable[[str, bool], int], manifest_dir: Path) -> Path:
    """Archive each item via ``patch(session_id, True)``; write the manifest first."""
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"archive-{time.strftime('%Y%m%d-%H%M%S')}.json"
    record = {"created_at": time.time(), "action": "archive", "items": items, "results": {}}
    path.write_text(json.dumps(record, indent=1))
    for item in items:
        record["results"][item["session_id"]] = patch(item["session_id"], True)
    path.write_text(json.dumps(record, indent=1))
    return path


def restore(manifest: Path, patch: Callable[[str, bool], int]) -> dict[str, int]:
    record = json.loads(manifest.read_text())
    return {item["session_id"]: patch(item["session_id"], False) for item in record.get("items", [])}


def _gateway(base: str = "http://127.0.0.1:8810"):  # pragma: no cover - live wiring
    import urllib.error
    import urllib.parse
    import urllib.request

    from jaeger_ai.core.gateway import caller_auth

    headers = {**caller_auth.client_headers("cli"), "Content-Type": "application/json"}

    def get_rows() -> list[dict[str, Any]]:
        req = urllib.request.Request(f"{base}/v1/sessions", headers=headers)
        data = json.load(urllib.request.urlopen(req, timeout=30))
        return data.get("sessions", data) if isinstance(data, dict) else data

    def patch(session_id: str, archived: bool) -> int:
        url = f"{base}/v1/sessions/{urllib.parse.quote(session_id, safe='')}"
        req = urllib.request.Request(url, data=json.dumps({"archived": archived}).encode(),
                                     headers=headers, method="PATCH")
        try:
            return urllib.request.urlopen(req, timeout=30).status
        except urllib.error.HTTPError as exc:
            return exc.code

    return get_rows, patch


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", type=Path)
    ap.add_argument("--manifests", type=Path, default=Path.home() / ".jaeger" / "archive-manifests")
    args = ap.parse_args(argv)
    get_rows, patch = _gateway()
    if args.restore:
        print(json.dumps(restore(args.restore, patch), indent=1))
        return 0
    rows = get_rows()
    items = plan(rows)
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[classify(row)[0]] = kinds.get(classify(row)[0], 0) + 1
    print(json.dumps({"sessions": len(rows), "kinds": kinds, "to_archive": len(items)}, indent=1))
    for item in items:
        print(f"  {item['session_id'][:40]:40}  {item['reason']:28}  {item['title'][:50]}")
    if args.apply:
        path = apply(items, patch, args.manifests)
        bad = {k: v for k, v in json.loads(path.read_text())["results"].items() if v != 200}
        print(f"manifest: {path}  failures: {bad or 'none'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
