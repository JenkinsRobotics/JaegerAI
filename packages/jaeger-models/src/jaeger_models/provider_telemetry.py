"""Live LLM provider API telemetry, pricing catalog, rate-limit headers & SQLite usage ledger.

Pulls official documented metadata from:
  - Local Ollama (`/api/tags`, `/api/ps`)
  - Ollama Cloud (`https://ollama.com/api/balance`, `https://ollama.com/api/usage?range=7d&group_by=model`)
  - OpenRouter (`https://openrouter.ai/api/v1/models`, `https://openrouter.ai/api/v1/key`)
  - OpenAI / Anthropic / Gemini rate-limit response headers (`x-ratelimit-*`, `anthropic-ratelimit-*`, `Retry-After`)

Pure stdlib + embedded SQLite WAL (zero external infrastructure daemons).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Standard per-1M-token (MTok) pricing and governance metadata for a model."""

    model_id: str
    provider: str
    input_per_mtok_usd: float = 0.0
    output_per_mtok_usd: float = 0.0
    cached_input_per_mtok_usd: float = 0.0
    context_length: int = 32768
    data_residency: str = "local_on_device"  # local_on_device | cloud_zdr | cloud_standard
    concurrency_limit: int | None = None
    pricing_source: str = "estimated"  # live_api | local_free | estimated

    def estimate_turn_cost_usd(
        self,
        *,
        prompt_tokens: int = 2000,
        completion_tokens: int = 600,
        cached_tokens: int = 0,
    ) -> float:
        billable_prompt = max(0, int(prompt_tokens) - max(0, int(cached_tokens)))
        cost = (
            (billable_prompt / 1_000_000.0) * self.input_per_mtok_usd
            + (max(0, int(cached_tokens)) / 1_000_000.0) * self.cached_input_per_mtok_usd
            + (max(0, int(completion_tokens)) / 1_000_000.0) * self.output_per_mtok_usd
        )
        return round(cost, 6)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["est_cost_per_1k_turns_usd"] = round(
            self.estimate_turn_cost_usd(prompt_tokens=2000, completion_tokens=600) * 1000.0,
            4,
        )
        return d


@dataclass(frozen=True, slots=True)
class RateLimitSnapshot:
    """Normalized rate-limit headroom parsed from OpenAI / Anthropic / HTTP 429 headers."""

    provider: str = ""
    rpm_limit: int | None = None
    rpm_remaining: int | None = None
    tpm_limit: int | None = None
    tpm_remaining: int | None = None
    itpm_limit: int | None = None
    itpm_remaining: int | None = None
    otpm_limit: int | None = None
    otpm_remaining: int | None = None
    retry_after_s: float | None = None
    reset_requests: str = ""
    reset_tokens: str = ""
    captured_at: float = field(default_factory=time.time)

    @property
    def low_headroom(self) -> bool:
        if self.retry_after_s is not None and self.retry_after_s > 0:
            return True
        for lim, rem in (
            (self.rpm_limit, self.rpm_remaining),
            (self.tpm_limit, self.tpm_remaining),
            (self.itpm_limit, self.itpm_remaining),
            (self.otpm_limit, self.otpm_remaining),
        ):
            if lim and rem is not None and (rem / max(1, lim)) <= 0.10:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["low_headroom"] = self.low_headroom
        return d


def _parse_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _parse_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def parse_rate_limit_headers(headers: Mapping[str, Any], *, provider: str = "") -> RateLimitSnapshot:
    """Parse OpenAI, Anthropic, and standard Retry-After rate-limit HTTP response headers."""
    low = {str(k).strip().lower(): str(v).strip() for k, v in (headers or {}).items()}
    detected = provider
    if not detected:
        if any(k.startswith("anthropic-ratelimit-") for k in low):
            detected = "anthropic"
        elif any(k.startswith("x-ratelimit-") for k in low):
            detected = "openai"
    return RateLimitSnapshot(
        provider=detected,
        rpm_limit=_parse_int(low.get("x-ratelimit-limit-requests") or low.get("anthropic-ratelimit-requests-limit")),
        rpm_remaining=_parse_int(low.get("x-ratelimit-remaining-requests") or low.get("anthropic-ratelimit-requests-remaining")),
        tpm_limit=_parse_int(low.get("x-ratelimit-limit-tokens") or low.get("anthropic-ratelimit-tokens-limit")),
        tpm_remaining=_parse_int(low.get("x-ratelimit-remaining-tokens") or low.get("anthropic-ratelimit-tokens-remaining")),
        itpm_limit=_parse_int(low.get("anthropic-ratelimit-input-tokens-limit")),
        itpm_remaining=_parse_int(low.get("anthropic-ratelimit-input-tokens-remaining")),
        otpm_limit=_parse_int(low.get("anthropic-ratelimit-output-tokens-limit")),
        otpm_remaining=_parse_int(low.get("anthropic-ratelimit-output-tokens-remaining")),
        retry_after_s=_parse_float(low.get("retry-after")),
        reset_requests=low.get("x-ratelimit-reset-requests") or low.get("anthropic-ratelimit-requests-reset") or "",
        reset_tokens=low.get("x-ratelimit-reset-tokens") or low.get("anthropic-ratelimit-tokens-reset") or "",
    )


# Reference fallback pricing (USD per 1M tokens) when live pricing APIs aren't queried.
_REFERENCE_PRICING: dict[str, tuple[float, float, int]] = {
    "deepseek-v4-pro": (0.55, 2.19, 131072),
    "deepseek-v4-flash": (0.14, 0.28, 131072),
    "deepseek-r1": (0.55, 2.19, 131072),
    "mistral-large": (2.00, 6.00, 131072),
    "qwen3.5:397b": (0.60, 2.40, 131072),
    "kimi-k2": (0.60, 2.50, 131072),
    "glm-5.3-flash": (0.10, 0.40, 131072),
    "glm-5": (0.50, 2.00, 131072),
    "gpt-oss:120b": (0.30, 1.00, 131072),
    "claude-sonnet": (3.00, 15.00, 200000),
    "claude-haiku": (1.00, 5.00, 200000),
    "claude-opus": (15.00, 75.00, 200000),
    "gpt-4o": (2.50, 10.00, 128000),
    "gpt-4o-mini": (0.15, 0.60, 128000),
    "gemini-3-flash": (0.15, 0.60, 1000000),
    "gemini-2.5-pro": (1.25, 10.00, 1000000),
}


def estimate_model_pricing(
    model_id: str,
    *,
    provider: str = "",
    size_bytes: int | None = None,
    live_openrouter_map: Mapping[str, ModelPricing] | None = None,
) -> ModelPricing:
    """Resolve pricing and data residency for a cloud or local model."""
    mid = (model_id or "").strip()
    low = mid.lower()
    if live_openrouter_map and low in live_openrouter_map:
        return live_openrouter_map[low]

    is_cloud = (
        ":cloud" in low
        or "-cloud" in low
        or provider.lower() in ("openai", "anthropic", "openrouter", "gemini", "google", "ollama_cloud")
        or (size_bytes is not None and 0 < size_bytes < 50_000)  # Ollama cloud pointer stubs are ~300 bytes
        or low.startswith(("gpt-", "claude-", "gemini-", "o1", "o3"))
    )
    if not is_cloud:
        return ModelPricing(
            model_id=mid,
            provider=provider or "ollama_local",
            input_per_mtok_usd=0.0,
            output_per_mtok_usd=0.0,
            cached_input_per_mtok_usd=0.0,
            context_length=32768,
            data_residency="local_on_device",
            concurrency_limit=1,  # 32 GB Apple Silicon single heavy model discipline
            pricing_source="local_free",
        )

    prov = provider or ("ollama_cloud" if (":cloud" in low or "-cloud" in low) else "cloud")
    concurrency = 3 if prov == "ollama_cloud" else None
    for prefix, (inp, out, ctx) in _REFERENCE_PRICING.items():
        if prefix in low:
            return ModelPricing(
                model_id=mid,
                provider=prov,
                input_per_mtok_usd=inp,
                output_per_mtok_usd=out,
                cached_input_per_mtok_usd=round(inp * 0.25, 4),
                context_length=ctx,
                data_residency="cloud_standard",
                concurrency_limit=concurrency,
                pricing_source="estimated",
            )
    return ModelPricing(
        model_id=mid,
        provider=prov,
        input_per_mtok_usd=1.00,
        output_per_mtok_usd=4.00,
        cached_input_per_mtok_usd=0.25,
        context_length=128000,
        data_residency="cloud_standard",
        concurrency_limit=concurrency,
        pricing_source="estimated",
    )


def _http_get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 8.0,
) -> tuple[dict[str, Any] | list[Any], dict[str, str]]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "JaegerAI-ModelTelemetry/1.0",
            **dict(headers or {}),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
        raw = resp.read(2_000_000).decode("utf-8", errors="replace")
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return json.loads(raw), hdrs


def fetch_ollama_cloud_telemetry(
    *,
    api_key: str | None = None,
    usage_range: str = "7d",
    timeout_s: float = 8.0,
    fetcher: Callable[..., tuple[Any, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Query Ollama Cloud's official `/api/balance` and `/api/usage?group_by=model` endpoints."""
    key = (api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY") or "").strip()
    if not key:
        return {
            "ok": False,
            "configured": False,
            "provider": "ollama_cloud",
            "error": "OLLAMA_API_KEY not set (set it to inspect live Ollama Cloud balance & per-model usage)",
        }
    do_get = fetcher or _http_get_json
    auth = {"Authorization": f"Bearer {key}"}
    out: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "provider": "ollama_cloud",
        "balance": None,
        "usage": None,
        "rate_limit": None,
        "errors": [],
    }
    try:
        bal, hdrs = do_get("https://ollama.com/api/balance", headers=auth, timeout_s=timeout_s)
        out["balance"] = bal
        out["rate_limit"] = parse_rate_limit_headers(hdrs, provider="ollama_cloud").to_dict()
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"balance: {exc}")
    try:
        qs = urllib.parse.urlencode({"range": usage_range, "group_by": "model"})
        usage, _ = do_get(f"https://ollama.com/api/usage?{qs}", headers=auth, timeout_s=timeout_s)
        out["usage"] = usage
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"usage: {exc}")
    if out["balance"] is None and out["usage"] is None:
        out["ok"] = False
    return out


def fetch_openrouter_telemetry(
    *,
    api_key: str | None = None,
    include_catalog: bool = True,
    catalog_limit: int = 100,
    timeout_s: float = 10.0,
    fetcher: Callable[..., tuple[Any, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Query OpenRouter `/api/v1/models` (exact per-MTok pricing) and `/api/v1/key` (credits/limits)."""
    key = (api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY") or "").strip()
    do_get = fetcher or _http_get_json
    out: dict[str, Any] = {
        "ok": True,
        "configured": bool(key),
        "provider": "openrouter",
        "key_status": None,
        "models": [],
        "model_count": 0,
        "errors": [],
    }
    if key:
        try:
            key_data, _ = do_get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout_s=timeout_s,
            )
            out["key_status"] = key_data.get("data") if isinstance(key_data, Mapping) and "data" in key_data else key_data
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"key: {exc}")
    if include_catalog:
        try:
            hdrs = {"Authorization": f"Bearer {key}"} if key else {}
            raw_cat, _ = do_get("https://openrouter.ai/api/v1/models", headers=hdrs, timeout_s=timeout_s)
            rows = raw_cat.get("data") if isinstance(raw_cat, Mapping) else raw_cat
            parsed: list[dict[str, Any]] = []
            for item in (rows or [])[: max(1, int(catalog_limit))]:
                if not isinstance(item, Mapping):
                    continue
                pricing = item.get("pricing") if isinstance(item.get("pricing"), Mapping) else {}
                p_tok = _parse_float(pricing.get("prompt")) or 0.0
                c_tok = _parse_float(pricing.get("completion")) or 0.0
                mid = str(item.get("id") or "")
                if not mid:
                    continue
                mp = ModelPricing(
                    model_id=mid,
                    provider="openrouter",
                    input_per_mtok_usd=round(p_tok * 1_000_000.0, 4),
                    output_per_mtok_usd=round(c_tok * 1_000_000.0, 4),
                    cached_input_per_mtok_usd=round(p_tok * 500_000.0, 4),
                    context_length=int(item.get("context_length") or 32768),
                    data_residency="cloud_standard",
                    pricing_source="live_api",
                )
                parsed.append(mp.to_dict())
            out["models"] = parsed
            out["model_count"] = len(parsed)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"models: {exc}")
    if out["key_status"] is None and not out["models"] and out["errors"]:
        out["ok"] = False
    return out


class ModelUsageLedger:
    """Embedded SQLite WAL ledger tracking per-model token burn, USD cost, latency & rate limits."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    ttft_ms INTEGER NOT NULL DEFAULT 0,
                    tps REAL NOT NULL DEFAULT 0.0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                    http_status INTEGER NOT NULL DEFAULT 200,
                    rate_limited INTEGER NOT NULL DEFAULT 0,
                    rate_limit_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_model_ts
                    ON model_usage_events(model_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS model_risk_cards (
                    model_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def record_call(
        self,
        *,
        model_id: str,
        provider: str,
        prompt_tokens: int = 0,
        cached_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int = 0,
        latency_ms: int = 0,
        ttft_ms: int = 0,
        tps: float = 0.0,
        estimated_cost_usd: float | None = None,
        http_status: int = 200,
        rate_limit: RateLimitSnapshot | Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = time.time() if now is None else float(now)
        if estimated_cost_usd is None:
            pricing = estimate_model_pricing(model_id, provider=provider)
            estimated_cost_usd = pricing.estimate_turn_cost_usd(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens + reasoning_tokens,
                cached_tokens=cached_tokens,
            )
        rl_dict = (
            rate_limit.to_dict()
            if isinstance(rate_limit, RateLimitSnapshot)
            else dict(rate_limit or {})
        )
        rate_limited = 1 if (http_status == 429 or rl_dict.get("low_headroom")) else 0
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_usage_events (
                    model_id, provider, prompt_tokens, cached_tokens, completion_tokens,
                    reasoning_tokens, latency_ms, ttft_ms, tps, estimated_cost_usd,
                    http_status, rate_limited, rate_limit_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(model_id),
                    str(provider),
                    int(prompt_tokens),
                    int(cached_tokens),
                    int(completion_tokens),
                    int(reasoning_tokens),
                    int(latency_ms),
                    int(ttft_ms),
                    float(tps),
                    float(estimated_cost_usd),
                    int(http_status),
                    rate_limited,
                    json.dumps(rl_dict, ensure_ascii=True),
                    ts,
                ),
            )
        return {
            "model_id": model_id,
            "provider": provider,
            "estimated_cost_usd": round(float(estimated_cost_usd), 6),
            "rate_limited": bool(rate_limited),
        }

    def summarize(self, *, window_days: float = 7.0) -> dict[str, Any]:
        since = time.time() - max(0.01, float(window_days)) * 86400.0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    model_id,
                    provider,
                    COUNT(*) AS calls,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(cached_tokens) AS cached_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(reasoning_tokens) AS reasoning_tokens,
                    AVG(latency_ms) AS avg_latency_ms,
                    AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END) AS avg_ttft_ms,
                    AVG(CASE WHEN tps > 0 THEN tps END) AS avg_tps,
                    SUM(estimated_cost_usd) AS total_cost_usd,
                    SUM(rate_limited) AS rate_limit_hits,
                    MAX(created_at) AS last_used_at
                FROM model_usage_events
                WHERE created_at >= ?
                GROUP BY model_id, provider
                ORDER BY total_cost_usd DESC, calls DESC
                """,
                (since,),
            ).fetchall()
            latest_rl: dict[str, dict[str, Any]] = {}
            for r in rows:
                rl_row = conn.execute(
                    """
                    SELECT rate_limit_json FROM model_usage_events
                    WHERE model_id = ? AND rate_limit_json != '{}'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (r["model_id"],),
                ).fetchone()
                if rl_row:
                    try:
                        latest_rl[r["model_id"]] = json.loads(rl_row["rate_limit_json"])
                    except json.JSONDecodeError:
                        pass

        models = []
        total_cost = 0.0
        total_calls = 0
        for r in rows:
            cost = round(float(r["total_cost_usd"] or 0.0), 6)
            total_cost += cost
            total_calls += int(r["calls"] or 0)
            models.append({
                "model_id": r["model_id"],
                "provider": r["provider"],
                "calls": int(r["calls"] or 0),
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "cached_tokens": int(r["cached_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "reasoning_tokens": int(r["reasoning_tokens"] or 0),
                "avg_latency_ms": round(float(r["avg_latency_ms"] or 0.0), 1),
                "avg_ttft_ms": round(float(r["avg_ttft_ms"] or 0.0), 1),
                "avg_tps": round(float(r["avg_tps"] or 0.0), 1),
                "total_cost_usd": cost,
                "rate_limit_hits": int(r["rate_limit_hits"] or 0),
                "last_used_at": r["last_used_at"],
                "latest_rate_limit": latest_rl.get(r["model_id"]),
            })
        return {
            "window_days": window_days,
            "total_calls": total_calls,
            "total_estimated_cost_usd": round(total_cost, 6),
            "models": models,
        }

    def save_risk_card(self, model_id: str, provider: str, card: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_risk_cards (model_id, provider, card_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    provider = excluded.provider,
                    card_json = excluded.card_json,
                    updated_at = excluded.updated_at
                """,
                (str(model_id), str(provider), json.dumps(dict(card), ensure_ascii=True), time.time()),
            )

    def get_risk_card(self, model_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT card_json, updated_at FROM model_risk_cards WHERE model_id = ?",
                (str(model_id),),
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["card_json"])
            data["stored_at"] = row["updated_at"]
            return data
        except json.JSONDecodeError:
            return None

    def list_risk_cards(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT card_json, updated_at FROM model_risk_cards ORDER BY updated_at DESC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                data = json.loads(row["card_json"])
                data["stored_at"] = row["updated_at"]
                out.append(data)
            except json.JSONDecodeError:
                continue
        return out


__all__ = [
    "ModelPricing",
    "ModelUsageLedger",
    "RateLimitSnapshot",
    "estimate_model_pricing",
    "fetch_ollama_cloud_telemetry",
    "fetch_openrouter_telemetry",
    "parse_rate_limit_headers",
]
