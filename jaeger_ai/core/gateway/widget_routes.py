"""AI-generated dashboard widgets (Jenkins Robotics, 2026-10-30, original).

``POST /v1/widgets/generate`` turns an operator's plain-language ask ("show me
pending approvals this week") into a validated, declarative widget spec that the
UI renders against real gateway data. It never executes model output: the model
returns JSON, and ``validate_spec`` re-checks every field against a closed schema
before the spec is returned to the caller.

Design rules (binding):
  * The spec is DATA, not code. There is no `load`/`view` function in it — only
    a source name, metric keys, a chart kind and display copy. The UI has the
    rendering primitives; the model picks among them.
  * Every metric must reference a field the gateway actually reports today
    (see ``_SOURCE_SCHEMAS``). Unknown sources or keys are rejected with 422,
    never guessed.
  * The endpoint needs the instance's external model configured; without it the
    caller gets 503 with a plain reason. Auth is the gateway's normal caller
    auth — the browser never sees a token (the WebUI proxy attaches it).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Closed schema: what an AI widget spec may contain.
# ---------------------------------------------------------------------------

SPEC_VERSION = 1

#: Sources the UI knows how to read. Keys = paths into JaegerSource.
#: `fields` below are the only keys a metric/filter may reference.
SOURCE_SCHEMAS: dict[str, dict[str, Any]] = {
    "diagnostics": {
        "description": "Gateway runtime counters (sessions, request outcomes, approvals).",
        "fields": {
            "sessions": "total sessions known to the gateway (number)",
            "requests.<outcome>": "count of requests by outcome verb, e.g. requests.completed",
            "approvals.<state>": "count of approvals by state, e.g. approvals.pending",
            "handoffs.<state>": "count of handoffs by state",
            "unknown_requests": "count of requests with unknown outcome",
            "process_id": "gateway process id",
            "observed_at": "unix time the snapshot was taken",
        },
    },
    "sessions": {
        "description": "Session rows (id, agent, title, timestamps, state).",
        "fields": {
            "count": "number of session rows returned",
            "state": "per-row session state verb",
            "agent_id": "per-row agent id",
        },
    },
    "agents": {
        "description": "Configured agents (id, name, role, state).",
        "fields": {
            "count": "number of agents returned",
            "state": "per-row agent state",
        },
    },
    "tasks": {
        "description": "Tasks known to the gateway (id, status, title).",
        "fields": {
            "count": "number of tasks returned",
            "status": "per-row task status verb",
        },
    },
    "approvals": {
        "description": "Pending approvals awaiting the operator.",
        "fields": {
            "count": "number of pending approvals",
        },
    },
}

CHART_KINDS = frozenset({"none", "stat", "bar", "sparkline", "list"})
SIZES = frozenset({"sm", "md", "lg"})
HOSTS = frozenset({"page", "float", "overlay"})

_TITLE_RE = re.compile(r"^[\w .,'’&()\-/]{2,60}$")
_TEXT_RE = re.compile(r"^[\w .,'’&()\-/:!?]{2,140}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$")


def _field_known(source: str, key: str) -> bool:
    schema = SOURCE_SCHEMAS.get(source)
    if schema is None:
        return False
    if key in schema["fields"]:
        return True
    # wildcard families: requests.<outcome>, approvals.<state>, handoffs.<state>
    head, _, tail = key.partition(".")
    return head in ("requests", "approvals", "handoffs") and bool(tail) and _KEY_RE.match(key) is not None


def validate_spec(raw: Any) -> dict[str, Any]:
    """Validate an untrusted spec dict. Returns a normalised copy or raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("spec must be a JSON object")
    v = raw.get("v")
    if v != SPEC_VERSION:
        raise ValueError(f"unsupported spec version {v!r}")

    source = raw.get("source")
    if not isinstance(source, str) or source not in SOURCE_SCHEMAS:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCE_SCHEMAS))}")

    title = raw.get("title")
    if not isinstance(title, str) or not _TITLE_RE.match(title):
        raise ValueError("title must be 2-60 plain characters")

    about = raw.get("about")
    if not isinstance(about, str) or not _TEXT_RE.match(about):
        raise ValueError("about must be 2-140 plain characters")

    metrics_raw = raw.get("metrics")
    if not isinstance(metrics_raw, list) or not 1 <= len(metrics_raw) <= 6:
        raise ValueError("metrics must be a list of 1-6 entries")
    metrics: list[dict[str, str]] = []
    for m in metrics_raw:
        if not isinstance(m, dict):
            raise ValueError("each metric must be an object")
        key, label = m.get("key"), m.get("label")
        if not isinstance(key, str) or not _KEY_RE.match(key) or not _field_known(source, key):
            raise ValueError(f"unknown metric key {key!r} for source {source!r}")
        if not isinstance(label, str) or not _TEXT_RE.match(label):
            raise ValueError(f"bad label for metric {key!r}")
        metrics.append({"key": key, "label": label})

    chart = raw.get("chart", "none")
    if chart not in CHART_KINDS:
        raise ValueError(f"chart must be one of: {', '.join(sorted(CHART_KINDS))}")

    size = raw.get("size", "md")
    if size not in SIZES:
        raise ValueError(f"size must be one of: {', '.join(sorted(SIZES))}")
    hosts_raw = raw.get("hosts", ["page"])
    if not isinstance(hosts_raw, list) or not hosts_raw or not all(h in HOSTS for h in hosts_raw):
        raise ValueError("hosts must be a non-empty list from: page, float, overlay")

    return {
        "v": SPEC_VERSION,
        "source": source,
        "title": title,
        "about": about,
        "metrics": metrics,
        "chart": chart,
        "size": size,
        "hosts": hosts_raw,
    }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You design dashboard widgets for Jaeger, a local AI companion.
Respond with ONE JSON object and nothing else. No markdown fences, no prose.

The object must have this exact shape:
{
  "v": 1,
  "source": "diagnostics" | "sessions" | "agents" | "tasks" | "approvals",
  "title": "short widget title, 2-60 plain chars",
  "about": "one-sentence description of what it shows, 2-140 plain chars",
  "metrics": [{"key": "<field>", "label": "<short label>"}],   // 1-6 entries
  "chart": "none" | "stat" | "bar" | "sparkline" | "list",
  "size": "sm" | "md" | "lg",
  "hosts": ["page"]                                              // page, float, overlay
}

Available sources and the ONLY metric keys you may use:
{schema_doc}

Rules:
- Pick ONE source per widget. Never mix sources.
- metric "key" must be exactly one of that source's fields (use the wildcard
  form like "requests.failed" or "approvals.pending" where listed).
- "stat" for a single headline number, "bar" for comparing 2-6 metrics,
  "sparkline" for a trend over time, "list" for rows, "none" for text-only.
- Prefer the smallest size that fits the content: sm for one number, md for a
  few, lg for charts.
- Never invent fields, never include code, scripts, URLs or HTML."""


def _schema_doc() -> str:
    lines = []
    for name, schema in SOURCE_SCHEMAS.items():
        lines.append(f"- {name}: {schema['description']}")
        for field, desc in schema["fields"].items():
            lines.append(f"    {field} — {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def _load_external_client():
    """Build an ExternalModelClient from the instance config, or raise ValueError."""
    from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
    from jaeger_ai.core.instance.schemas import Config, load_yaml
    from jaeger_ai.core.models.external_model import ExternalModelClient

    layout = InstanceLayout(resolve_instance_dir())
    cfg_path = Path(layout.config_path)
    if not cfg_path.is_file():
        raise ValueError("no instance config.yaml found")
    cfg = load_yaml(cfg_path, Config)
    ext = getattr(cfg, "external_model", None)
    if ext is None or not getattr(ext, "enabled", False):
        raise ValueError("external model is not enabled in instance settings")
    return ExternalModelClient(ext, layout), ext


def generate_spec(prompt: str) -> dict[str, Any]:
    """One-shot text completion → validated spec. Raises ValueError on any failure."""
    client, ext = _load_external_client()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT.replace("{schema_doc}", _schema_doc())},
        {"role": "user", "content": prompt},
    ]
    result = client.chat(  # raises ExternalModelError on failure
        messages,
        max_tokens=min(int(getattr(ext, "max_tokens", 1024) or 1024), 2048),
        temperature=0.2,
    )
    text = (result.text or "").strip()
    # Tolerate a model that wraps JSON in fences despite instructions.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return JSON: {exc}") from exc
    return validate_spec(parsed)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

def register_widget_routes(app: web.Application) -> None:
    async def generate(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be a JSON object"}, status=400)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt or len(prompt) > 1000:
            return web.json_response({"error": "'prompt' must be 1-1000 characters"}, status=400)

        started = time.time()
        try:
            # Run the blocking LLM call in a thread so the event loop stays free.
            import asyncio
            loop = asyncio.get_running_loop()
            spec = await loop.run_in_executor(None, generate_spec, prompt)
        except ValueError as exc:
            message = str(exc)
            status = 503 if "not enabled" in message or "no instance config" in message else 422
            return web.json_response({"error": message}, status=status)
        except Exception as exc:  # model/API failure — never leak internals
            logger.warning("widget generation failed: %s", type(exc).__name__)
            return web.json_response({"error": "The model could not produce a widget right now."}, status=502)

        return web.json_response({"spec": spec, "latency_s": round(time.time() - started, 3)}, status=201)

    app.router.add_post("/v1/widgets/generate", generate)
    logger.info("Widget generation route registered: POST /v1/widgets/generate")
