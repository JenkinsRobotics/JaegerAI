"""Insights, LLM-Wiki status, and Project-OS dashboard route handlers.

Extracted from routes.py to isolate analytics, wiki stats, and project status logic.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import sqlite3
import stat as _stat
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs

from api.helpers import j
from api.models import SESSION_DIR
from api.workspace import (get_last_workspace, read_file_content)

logger = logging.getLogger(__name__)







































def _handle_insights(handler, parsed) -> bool:
    """Return usage analytics from local WebUI session data."""
    import time as _time

    from api.usage import prompt_cache_hit_percent

    query = parse_qs(parsed.query)
    try:
        days = min(max(int(query.get("days", ["30"])[0]), 1), 365)
    except (ValueError, TypeError):
        days = 30

    now = _time.time()
    today = _time.localtime(now)
    today_midnight = _time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, today.tm_wday, today.tm_yday, today.tm_isdst))
    day_secs = 86400
    first_day_ts = today_midnight - ((days - 1) * day_secs)
    cutoff = first_day_ts

    def _safe_usage_int(value) -> int:
        try:
            return max(int(float(value or 0)), 0)
        except (TypeError, ValueError):
            return 0

    def _safe_cost_float(value) -> float:
        if value is None:
            return 0.0
        try:
            if isinstance(value, str):
                value = value.strip().replace("$", "").replace(",", "")
                if not value:
                    return 0.0
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _session_usage_ts(session: dict) -> float:
        return session.get("updated_at", session.get("created_at", 0)) or session.get("created_at", 0) or 0

    # Walk session index (fast, no full JSON parse)
    sessions_data = []
    idx_path = SESSION_DIR / "_index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = []
    else:
        idx = []

    for entry in idx:
        created = entry.get("created_at", 0) or 0
        updated = entry.get("updated_at", 0) or 0
        # Session is relevant if it was created or updated within the calendar window.
        if max(created, updated) < cutoff:
            continue
        sessions_data.append(entry)

    # Aggregate
    total_sessions = len(sessions_data)
    total_messages = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cost = 0.0
    model_stats: dict[str, dict] = {}
    daily_tokens: dict[str, dict] = {}
    # Activity by day of week (0=Mon .. 6=Sun)
    dow_activity = collections.Counter()
    # Activity by hour of day (0-23)
    hod_activity = collections.Counter()

    for s in sessions_data:
        input_tokens = _safe_usage_int(s.get("input_tokens"))
        output_tokens = _safe_usage_int(s.get("output_tokens"))
        cache_read_tokens = _safe_usage_int(s.get("cache_read_tokens"))
        cost_value = _safe_cost_float(s.get("estimated_cost"))
        total_messages += _safe_usage_int(s.get("message_count"))
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cache_read_tokens += cache_read_tokens
        total_cost += cost_value

        model = s.get("model") or "unknown"
        bucket = model_stats.setdefault(model, {
            "sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 0.0,
        })
        bucket["sessions"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cache_read_tokens"] += cache_read_tokens
        bucket["cost"] += cost_value

        # Activity patterns
        ts = _session_usage_ts(s)
        if ts:
            try:
                dt = _time.localtime(ts)
                day_key = _time.strftime("%Y-%m-%d", dt)
                daily_bucket = daily_tokens.setdefault(day_key, {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "sessions": 0,
                    "cost": 0.0,
                })
                daily_bucket["input_tokens"] += input_tokens
                daily_bucket["output_tokens"] += output_tokens
                daily_bucket["cache_read_tokens"] += cache_read_tokens
                daily_bucket["sessions"] += 1
                daily_bucket["cost"] += cost_value
                dow_activity[dt.tm_wday] += 1
                hod_activity[dt.tm_hour] += 1
            except Exception:
                pass

    # ── Also include CLI sessions from Hermes state.db ─────────────────────
    try:
        from api.models import _active_state_db_path
        db_path = _active_state_db_path()
        if db_path and db_path.exists():
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # cache_read_tokens may not exist on older agent state DBs;
                # fall back to a query without it if the column is missing.
                try:
                    cur.execute("""
                        SELECT id, model, message_count, input_tokens, output_tokens,
                               estimated_cost_usd,
                               COALESCE(cache_read_tokens, 0) AS cache_read_tokens,
                               started_at, ended_at
                        FROM sessions
                        WHERE (started_at >= ? OR ended_at >= ?)
                          AND COALESCE(source, '') != 'webui'
                    """, (cutoff, cutoff))
                except sqlite3.OperationalError:
                    cur.execute("""
                        SELECT id, model, message_count, input_tokens, output_tokens,
                               estimated_cost_usd,
                               0 AS cache_read_tokens,
                               started_at, ended_at
                        FROM sessions
                        WHERE (started_at >= ? OR ended_at >= ?)
                          AND COALESCE(source, '') != 'webui'
                    """, (cutoff, cutoff))
                for row in cur.fetchall():
                    _input = _safe_usage_int(row["input_tokens"])
                    _output = _safe_usage_int(row["output_tokens"])
                    _cache_read = _safe_usage_int(row["cache_read_tokens"])
                    _cost = _safe_cost_float(row["estimated_cost_usd"])
                    _msgs = _safe_usage_int(row["message_count"])
                    total_sessions += 1
                    total_messages += _msgs
                    total_input_tokens += _input
                    total_output_tokens += _output
                    total_cache_read_tokens += _cache_read
                    total_cost += _cost

                    _model = row["model"] or "unknown"
                    bucket = model_stats.setdefault(_model, {
                        "sessions": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 0.0,
                    })
                    bucket["sessions"] += 1
                    bucket["input_tokens"] += _input
                    bucket["output_tokens"] += _output
                    bucket["cache_read_tokens"] += _cache_read
                    bucket["cost"] += _cost

                    _ts = row["started_at"] or row["ended_at"] or 0
                    if _ts:
                        _dt = _time.localtime(_ts)
                        _day_key = _time.strftime("%Y-%m-%d", _dt)
                        _daily = daily_tokens.setdefault(_day_key, {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_tokens": 0,
                            "sessions": 0,
                            "cost": 0.0,
                        })
                        _daily["input_tokens"] += _input
                        _daily["output_tokens"] += _output
                        _daily["cache_read_tokens"] += _cache_read
                        _daily["sessions"] += 1
                        _daily["cost"] += _cost
                        dow_activity[_dt.tm_wday] += 1
                        hod_activity[_dt.tm_hour] += 1
    except Exception:
        logger.debug("Failed to include CLI sessions in insights", exc_info=True)

    # Build model breakdown
    total_tokens = total_input_tokens + total_output_tokens
    models_breakdown = []
    for model, stats in model_stats.items():
        row_total_tokens = stats["input_tokens"] + stats["output_tokens"]
        row_cost = round(stats["cost"], 6)
        row_cache_read = stats["cache_read_tokens"]
        # Bounded prompt-cache hit rate: cached reads over the FULL prompt total
        # (ordinary input + cache reads), so it can never exceed 100%. Computing
        # cache_read / input_tokens alone would overshoot 100% on cache-heavy
        # sessions. prompt_cache_hit_percent clamps to [0,100] and returns None
        # when there is nothing meaningful to display.
        row_cache_hit_percent = prompt_cache_hit_percent(
            row_cache_read, stats["input_tokens"] + row_cache_read
        )
        models_breakdown.append({
            "model": model,
            "sessions": stats["sessions"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "cache_read_tokens": row_cache_read,
            "cache_hit_percent": row_cache_hit_percent,
            "total_tokens": row_total_tokens,
            "cost": row_cost,
            "session_share": int(round((stats["sessions"] / total_sessions) * 100)) if total_sessions else 0,
            "token_share": int(round((row_total_tokens / total_tokens) * 100)) if total_tokens else 0,
            "cost_share": int(round((row_cost / total_cost) * 100)) if total_cost else 0,
        })
    models_breakdown.sort(key=lambda r: (-r["cost"], -r["sessions"], r["model"]))

    daily_series = []
    for i in range(days):
        day_ts = first_day_ts + (i * day_secs)
        day_key = _time.strftime("%Y-%m-%d", _time.localtime(day_ts))
        bucket = daily_tokens.get(day_key, {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "sessions": 0,
            "cost": 0.0,
        })
        daily_series.append({
            "date": day_key,
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "cache_read_tokens": bucket.get("cache_read_tokens", 0),
            "sessions": bucket["sessions"],
            "cost": round(bucket["cost"], 6),
        })

    # Day-of-week labels
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_data = [{"day": dow_labels[i], "sessions": dow_activity.get(i, 0)} for i in range(7)]

    # Hour-of-day data
    hod_data = [{"hour": h, "sessions": hod_activity.get(h, 0)} for h in range(24)]

    return j(handler, {
        "period_days": days,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        # Aggregate prompt-cache hit rate, bounded 0-100% via the shared helper
        # (cache_read over input + cache_read).
        "total_cache_hit_percent": prompt_cache_hit_percent(
            total_cache_read_tokens, total_input_tokens + total_cache_read_tokens
        ),
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "models": models_breakdown,
        "daily_tokens": daily_series,
        "activity_by_day": dow_data,
        "activity_by_hour": hod_data,
    })




















