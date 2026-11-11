#!/usr/bin/env python3
"""Live smoke: every cloud provider — plain response + tool use.

Stdlib-first so it runs even when the repo venv is not on PATH. Uses
Jaeger credential resolution when importable; otherwise env vars +
~/.jaeger credentials files.

Providers:
  ollama-cloud, openai, anthropic, gemini, xai,
  openrouter, groq, deepseek, together

For each configured provider:

  1. RESPONSE — short chat completion must return non-empty text
  2. TOOL USE — model must emit a structured tool/function call

Usage:
    python3 dev/benchmark/cloud_provider_smoke.py
    python3 dev/benchmark/cloud_provider_smoke.py --providers openai,xai
    python3 dev/benchmark/cloud_provider_smoke.py --json-out ~/.jaeger/verification/cloud_smoke.json
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama-cloud": {
        "base_url": "https://ollama.com/v1",
        "model": "glm-5.3-flash:cloud",
        "kind": "openai",
        "env": ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY"),
        "cred": ("ollama_cloud_api_key", "ollama_api_key"),
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "kind": "openai",
        "env": ("OPENAI_API_KEY",),
        "cred": ("openai_api_key",),
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-6",
        "kind": "anthropic",
        "env": ("ANTHROPIC_API_KEY",),
        "cred": ("anthropic_api_key",),
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "kind": "openai",
        "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "cred": ("gemini_api_key", "google_api_key"),
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-1-fast-non-reasoning",
        "kind": "openai",
        "env": ("XAI_API_KEY", "GROK_API_KEY"),
        "cred": ("xai_api_key", "grok_api_key"),
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "kind": "openai",
        "env": ("OPENROUTER_API_KEY",),
        "cred": ("openrouter_api_key",),
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "kind": "openai",
        "env": ("GROQ_API_KEY",),
        "cred": ("groq_api_key",),
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "kind": "openai",
        "env": ("DEEPSEEK_API_KEY",),
        "cred": ("deepseek_api_key",),
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "kind": "openai",
        "env": ("TOGETHER_API_KEY",),
        "cred": ("together_api_key",),
    },
}

CALC_TOOL_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a simple arithmetic expression. Always use this for math.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Simple arithmetic expression, e.g. '2+2'",
                    }
                },
                "required": ["expression"],
            },
        },
    }
]

CALC_TOOL_ANTHROPIC = [
    {
        "name": "calculator",
        "description": "Evaluate a simple arithmetic expression. Always use this for math.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Simple arithmetic expression, e.g. '2+2'",
                }
            },
            "required": ["expression"],
        },
    }
]


@dataclass
class ProbeResult:
    provider: str
    model: str
    configured: bool
    response_ok: bool | None = None
    response_latency_ms: int = 0
    response_preview: str = ""
    response_error: str = ""
    tool_ok: bool | None = None
    tool_latency_ms: int = 0
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("JAEGER_INSTANCE_DIR", "JAEGER_STATE_DIR", "JAEGER_HOME"):
        val = (os.environ.get(env) or "").strip()
        if val:
            roots.append(Path(val).expanduser())
    roots.append(Path.home() / ".jaeger")
    # Dedup while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _read_cred_file(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def resolve_key(provider: str) -> str:
    meta = PROVIDERS[provider]
    # 1. env
    for env in meta["env"]:
        val = (os.environ.get(env) or "").strip()
        if val:
            return val
    # 2. credential files under known state roots
    for root in _state_roots():
        candidates = [
            root / "credentials",
            root / "default" / "credentials",
            root / "instances" / "default" / "credentials",
        ]
        # Also scan one level of instance dirs
        try:
            if root.is_dir():
                for child in root.iterdir():
                    if child.is_dir():
                        candidates.append(child / "credentials")
        except OSError:
            pass
        for cred_dir in candidates:
            if not cred_dir.is_dir():
                continue
            for name in meta["cred"]:
                val = _read_cred_file(cred_dir / name)
                if val:
                    return val
            # generic fallback
            val = _read_cred_file(cred_dir / "external_model_api_key")
            if val:
                return val
    # 3. try Jaeger resolver if importable
    try:
        repo = Path(__file__).resolve().parents[2]
        for extra in (
            repo,
            repo / "packages" / "jaeger-agent",
            repo / "packages" / "jaeger-os",
        ):
            s = str(extra)
            if s not in sys.path:
                sys.path.insert(0, s)
        from jaeger_ai.core.instance.schemas import ExternalModelConfig
        from jaeger_ai.core.models.external_model import resolve_api_key
        from jaeger_ai.core.instance.instance import resolve_instance_dir, InstanceLayout

        layout = InstanceLayout(root=Path(resolve_instance_dir(None)))
        ext = ExternalModelConfig(
            enabled=True,
            provider=provider,
            model=meta["model"],
            base_url=meta["base_url"],
        )
        val = (resolve_api_key(ext, layout) or "").strip()
        if val:
            return val
    except Exception:
        pass
    return ""


def _http_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = 90.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network: {exc.reason}") from None


def _openai_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 128,
    temperature: float = 0.0,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    return _http_json(url, payload, headers)


def _anthropic_chat(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    system: str = "",
    max_tokens: int = 128,
    temperature: float = 0.0,
) -> dict[str, Any]:
    url = "https://api.anthropic.com/v1/messages"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    return _http_json(url, payload, headers)


def test_response(provider: str, model: str, api_key: str) -> tuple[bool, int, str, str]:
    meta = PROVIDERS[provider]
    t0 = time.perf_counter()
    try:
        if meta["kind"] == "anthropic":
            raw = _anthropic_chat(
                api_key,
                model,
                [{"role": "user", "content": "Reply with exactly the word PONG and nothing else."}],
                system="You are a concise test harness.",
                max_tokens=64,
            )
            blocks = raw.get("content") or []
            text = ""
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    text += b.get("text") or ""
            text = text.strip()
        else:
            raw = _openai_chat(
                meta["base_url"],
                api_key,
                model,
                [{"role": "user", "content": "Reply with exactly the word PONG and nothing else."}],
                max_tokens=64,
            )
            choices = raw.get("choices") or []
            msg = (choices[0].get("message") if choices else {}) or {}
            text = (msg.get("content") or "").strip()
            # reasoning-only models may spend budget thinking
            if not text:
                usage = raw.get("usage") or {}
                finish = (choices[0].get("finish_reason") if choices else "") or ""
                if finish == "length" and int(usage.get("completion_tokens") or 0) > 0:
                    text = "(reasoning tokens only — inference OK)"
        ms = int((time.perf_counter() - t0) * 1000)
        if not text:
            return False, ms, "", "empty response"
        return True, ms, text.replace("\n", " ")[:120], ""
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return False, ms, "", f"{type(exc).__name__}: {exc}"[:400]


def test_tool_use(provider: str, model: str, api_key: str) -> tuple[bool, int, str, dict[str, Any], str]:
    meta = PROVIDERS[provider]
    prompt = (
        "Use the calculator tool to compute 17+25. "
        "Do not answer with the number yourself — you must call the calculator tool."
    )
    t0 = time.perf_counter()
    try:
        if meta["kind"] == "anthropic":
            raw = _anthropic_chat(
                api_key,
                model,
                [{"role": "user", "content": prompt}],
                tools=CALC_TOOL_ANTHROPIC,
                system="You are a tool-using assistant. Always call tools when asked to compute.",
                max_tokens=256,
            )
            blocks = raw.get("content") or []
            name = ""
            args: dict[str, Any] = {}
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    name = str(b.get("name") or "")
                    inp = b.get("input") or {}
                    args = inp if isinstance(inp, dict) else {"value": inp}
                    break
            ms = int((time.perf_counter() - t0) * 1000)
            if not name:
                text_bits = [
                    (b.get("text") or "")
                    for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                return False, ms, "", {}, f"no tool_use (content={''.join(text_bits)[:160]!r})"
            if name != "calculator":
                return False, ms, name, args, f"unexpected tool {name!r}"
            return True, ms, name, args, ""

        raw = _openai_chat(
            meta["base_url"],
            api_key,
            model,
            [
                {
                    "role": "system",
                    "content": "You are a tool-using assistant. Always call tools when asked to compute.",
                },
                {"role": "user", "content": prompt},
            ],
            tools=CALC_TOOL_OPENAI,
            max_tokens=256,
        )
        choices = raw.get("choices") or []
        msg = (choices[0].get("message") if choices else {}) or {}
        calls = msg.get("tool_calls") or []
        ms = int((time.perf_counter() - t0) * 1000)
        if not calls:
            return False, ms, "", {}, f"no tool_calls (content={(msg.get('content') or '')[:160]!r})"
        first = calls[0] or {}
        fn = first.get("function") or {}
        name = str(fn.get("name") or "")
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            if not isinstance(args, dict):
                args = {"value": args}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        if name != "calculator":
            return False, ms, name, args, f"unexpected tool {name!r}"
        return True, ms, name, args, ""
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return False, ms, "", {}, f"{type(exc).__name__}: {exc}"[:400]


def probe_one(provider: str, model_override: str | None) -> ProbeResult:
    meta = PROVIDERS[provider]
    model = model_override or str(meta["model"])
    key = resolve_key(provider)
    result = ProbeResult(provider=provider, model=model, configured=bool(key))
    if not key:
        return result

    print(f"\n=== {provider} / {model} ===")
    print("  response …", flush=True)
    ok, ms, preview, err = test_response(provider, model, key)
    result.response_ok = ok
    result.response_latency_ms = ms
    result.response_preview = preview
    result.response_error = err
    print(f"  response {'PASS' if ok else 'FAIL'} ({ms} ms) {preview or err}", flush=True)

    print("  tool use …", flush=True)
    tok, tms, tname, targs, terr = test_tool_use(provider, model, key)
    result.tool_ok = tok
    result.tool_latency_ms = tms
    result.tool_name = tname
    result.tool_args = targs
    result.tool_error = terr
    detail = f"{tname} {targs}" if tok else terr
    print(f"  tool use {'PASS' if tok else 'FAIL'} ({tms} ms) {detail}", flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--providers", default="", help="Comma-separated subset (default: all).")
    p.add_argument("--model", default="", help="Override model id for every selected provider.")
    p.add_argument("--json-out", default="", help="Optional JSON results path.")
    p.add_argument(
        "--configured-only",
        action="store_true",
        help="Skip unconfigured providers entirely (default still lists them as SKIP).",
    )
    args = p.parse_args(argv)

    selected = [s.strip() for s in args.providers.split(",") if s.strip()] or list(PROVIDERS)
    unknown = [s for s in selected if s not in PROVIDERS]
    if unknown:
        print(f"Unknown providers: {', '.join(unknown)}", file=sys.stderr)
        print(f"Known: {', '.join(PROVIDERS)}", file=sys.stderr)
        return 2

    print("Cloud provider smoke — response + tool use")
    print(f"Providers: {', '.join(selected)}")
    print(f"Started: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    results: list[ProbeResult] = []
    for name in selected:
        key = resolve_key(name)
        if not key:
            if args.configured_only:
                print(f"\n=== {name} ===\n  SKIP (no key, --configured-only)")
                continue
            print(f"\n=== {name} / {PROVIDERS[name]['model']} ===\n  SKIP (no API key in env or credentials)")
            results.append(ProbeResult(provider=name, model=str(PROVIDERS[name]["model"]), configured=False))
            continue
        results.append(probe_one(name, args.model or None))

    print("\n" + "=" * 78)
    print(f"{'provider':<14} {'model':<40} {'key':<5} {'resp':<6} {'tool':<6} {'ms'}")
    print("-" * 78)
    n_cfg = n_resp = n_tool = 0
    for r in results:
        if r.configured:
            n_cfg += 1
        if r.response_ok:
            n_resp += 1
        if r.tool_ok:
            n_tool += 1
        key_s = "yes" if r.configured else "no"
        resp_s = "—" if r.response_ok is None else ("PASS" if r.response_ok else "FAIL")
        tool_s = "—" if r.tool_ok is None else ("PASS" if r.tool_ok else "FAIL")
        ms = r.response_latency_ms + r.tool_latency_ms
        print(f"{r.provider:<14} {r.model:<40} {key_s:<5} {resp_s:<6} {tool_s:<6} {ms}")
    print("-" * 78)
    print(f"configured={n_cfg}/{len(results)}  response_pass={n_resp}/{n_cfg or 0}  tool_pass={n_tool}/{n_cfg or 0}")

    payload = {
        "suite": "cloud_provider_smoke",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": [r.as_dict() for r in results],
        "summary": {
            "configured": n_cfg,
            "total": len(results),
            "response_pass": n_resp,
            "tool_pass": n_tool,
        },
    }
    out = Path(args.json_out).expanduser() if args.json_out else (Path.home() / ".jaeger" / "verification" / "cloud_provider_smoke.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
    except OSError as exc:
        print(f"(could not write results: {exc})", file=sys.stderr)

    if n_cfg == 0:
        print("No cloud providers configured — nothing to test.", file=sys.stderr)
        return 3
    if n_resp < n_cfg or n_tool < n_cfg:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
