"""``GET /v1/usage``: sessions, messages and tokens per model, read (read-only)
from the Gateway session store. Replaces the Hermes insights that read the
retired WebUI's own session files (R11)."""
from __future__ import annotations

import collections
import json
import sqlite3
import time
from contextlib import closing
from urllib.parse import parse_qs


def _db():
    from jaeger_ai.core.gateway.session_store import default_store_path
    path = default_store_path(create=False)
    return closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5))


def _free(model: str) -> bool:
    """CLI subscriptions and Ollama are not billed per token."""
    return model.startswith(("cli:", "ollama", "@ollama")) or model.endswith(":cloud") or model == "unknown"


def usage(days: int) -> dict:
    since = time.time() - days * 86400
    per = collections.defaultdict(lambda: {"sessions": set(), "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cost": 0.0})
    daily = collections.defaultdict(lambda: {"sessions": set(), "input_tokens": 0, "output_tokens": 0})
    with _db() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE updated_at >= ?", (since,)).fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE timestamp >= ?", (since,)).fetchone()[0]
        rows = conn.execute("SELECT session_id, result_json, created_at FROM client_requests "
                            "WHERE created_at >= ? AND result_json IS NOT NULL", (since,)).fetchall()
    for sid, raw, created in rows:
        try:
            res = json.loads(raw or "{}")
        except ValueError:
            continue
        if not isinstance(res, dict):
            continue
        model = str(res.get("actual_model") or res.get("model") or "unknown")
        u = ((res.get("timing") or {}).get("usage") or {}) if isinstance(res.get("timing"), dict) else {}
        inp, out = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        m = per[model]
        m["sessions"].add(sid)
        m["input_tokens"] += inp
        m["output_tokens"] += out
        m["cache_read_tokens"] += int(u.get("cache_read_tokens") or 0)
        if not _free(model):
            m["cost"] += float(u.get("cost_usd") or 0.0)
        day = time.strftime("%Y-%m-%d", time.localtime(created))
        d = daily[day]
        d["sessions"].add(sid)
        d["input_tokens"] += inp
        d["output_tokens"] += out
    tot_tokens = sum(m["input_tokens"] + m["output_tokens"] for m in per.values())
    tot_cost = round(sum(m["cost"] for m in per.values()), 4)
    model_sessions = sum(len(m["sessions"]) for m in per.values()) or 1
    models = []
    for name, m in sorted(per.items(), key=lambda kv: -(kv[1]["input_tokens"] + kv[1]["output_tokens"])):
        t = m["input_tokens"] + m["output_tokens"]
        models.append({"model": name, "sessions": len(m["sessions"]), "input_tokens": m["input_tokens"],
                       "output_tokens": m["output_tokens"], "cache_read_tokens": m["cache_read_tokens"],
                       "cache_hit_percent": None, "total_tokens": t, "cost": round(m["cost"], 4),
                       "session_share": round(100 * len(m["sessions"]) / model_sessions),
                       "token_share": round(100 * t / tot_tokens) if tot_tokens else 0,
                       "cost_share": round(100 * m["cost"] / tot_cost) if tot_cost else 0})
    return {"period_days": days, "total_sessions": total_sessions, "total_messages": total_messages,
            "total_input_tokens": sum(m["input_tokens"] for m in per.values()),
            "total_output_tokens": sum(m["output_tokens"] for m in per.values()),
            "total_cache_read_tokens": sum(m["cache_read_tokens"] for m in per.values()),
            "total_cache_hit_percent": None, "total_tokens": tot_tokens, "total_cost": tot_cost, "models": models,
            "daily_tokens": [{"date": k, "sessions": len(v["sessions"]), "input_tokens": v["input_tokens"],
                              "output_tokens": v["output_tokens"]} for k, v in sorted(daily.items())],
            "source": "gateway_sessions"}


def _handle_insights(handler, parsed):
    from api.helpers import j
    try:
        days = max(1, min(365, int((parse_qs(parsed.query or "").get("days") or ["30"])[0])))
    except ValueError:
        days = 30
    return j(handler, usage(days))
