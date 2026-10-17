"""Proxy WebUI /api/agents* to the Jaeger Gateway's /v1/agents*.

Browser clients on :8790 cannot reliably reach the loopback Gateway; the WebUI
process proxies server-side. Chat spine is Gateway — not ARES :8813.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def runner_base() -> str:
    """The Jaeger runner (:8791), which owns per-framework execution.

    Distinct from :func:`gateway_base` (the Gateway). The session index lives on the
    runner because that is the process holding the framework adapters; sending
    it to the gateway would 404, and the two ports are one digit apart.
    """
    return (
        os.environ.get("HERMES_WEBUI_RUNNER_BASE_URL")
        or os.environ.get("JAEGER_RUNNER_BASE_URL")
        or "http://127.0.0.1:8791"
    ).rstrip("/")


def gateway_base() -> str:
    return (
        os.environ.get("JAEGER_GATEWAY_URL")
        or os.environ.get("HERMES_WEBUI_GATEWAY_URL")
        or _resolved_gateway_url()
    ).rstrip("/")


def _resolved_gateway_url() -> str:
    """The Gateway URL from contract.ports (env overrides honoured)."""
    from jaeger_ai.contract.ports import resolve_gateway_url
    return resolve_gateway_url()


def _proxy(handler, method: str, path: str, body: bytes | None = None,
           base: str | None = None) -> bool:
    from api.helpers import bad, j

    url = f"{base or gateway_base()}{path}"
    data = body if method.upper() in {"POST", "PUT", "PATCH"} else None
    req = Request(url, data=data, method=method.upper())
    req.add_header("Accept", "application/json")
    from jaeger_ai.core.gateway.caller_auth import client_headers
    for key, value in client_headers("webui").items():
        req.add_header(key, value)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=8) as resp:
            payload = resp.read()
            try:
                parsed = json.loads(payload.decode("utf-8") or "null")
            except json.JSONDecodeError:
                bad(handler, "gateway returned non-JSON", 502)
                return True
            j(handler, parsed, status=int(getattr(resp, "status", 200) or 200))
            return True
    except HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            parsed = {"error": exc.reason}
        j(handler, parsed, status=int(exc.code))
        return True
    except (OSError, URLError) as exc:
        bad(handler, f"gateway unreachable: {exc}", 503)
        return True


def avatar_model_path():
    """The one VRM the WebUI avatar may load: JAEGER_AVATAR_VRM, else the first
    ``*.vrm`` in ~/.jaeger/assets/avatar. Runtime asset, never in git."""
    from pathlib import Path

    raw = (os.environ.get("JAEGER_AVATAR_VRM") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_file() and path.suffix.lower() == ".vrm" else None
    folder = Path.home() / ".jaeger" / "assets" / "avatar"
    found = sorted(folder.glob("*.vrm")) if folder.is_dir() else []
    return found[0] if found else None


def _serve_avatar_model(handler) -> bool:
    path = avatar_model_path()
    if path is None:
        body = b'{"error":"no avatar model installed"}'
        handler.send_response(404)
        handler.send_header("Content-Type", "application/json")
    else:
        body = path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "model/gltf-binary")
        handler.send_header("Cache-Control", "private, max-age=86400")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


_KOKORO = None
_KOKORO_LOCK = None
KOKORO_MAX_CHARS = 600


def kokoro_wav(text: str) -> bytes | None:
    """Jaeger's local voice (Kokoro, offline) as a 16-bit mono WAV, or None.

    One lazily loaded engine per WebUI process; renders are serialized. Opens
    no audio device; the browser plays the clip, so the avatar's mouth can
    follow its real level.
    """
    global _KOKORO, _KOKORO_LOCK
    import io
    import threading
    import wave

    text = (text or "").strip()[:KOKORO_MAX_CHARS]
    if not text:
        return None
    if _KOKORO_LOCK is None:
        _KOKORO_LOCK = threading.Lock()
    with _KOKORO_LOCK:
        if _KOKORO is None:
            from jaeger_kokoro_tts.engine import KokoroTTS
            _KOKORO = KokoroTTS()
        audio = _KOKORO.render(text)
    if audio is None or len(audio) == 0:
        return None
    import numpy as np
    from jaeger_kokoro_tts.engine import KOKORO_SAMPLE_RATE

    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(KOKORO_SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def warm_kokoro_in_background():
    """Load Kokoro and render one short line off the request path, so the first
    speak-first message is not 7-12 s late. Opens no audio device. Off with
    JAEGER_KOKORO_WARM=0. Returns the thread, or None when disabled."""
    import threading

    if (os.environ.get("JAEGER_KOKORO_WARM") or "1").strip() == "0":
        return None

    def _warm():
        try:
            kokoro_wav("Ready.")
            print("[jaeger] Kokoro voice warm", flush=True)
        except Exception as exc:  # optional: the companion falls back to browser speech
            print(f"[jaeger] Kokoro warm skipped: {type(exc).__name__}", flush=True)

    t = threading.Thread(target=_warm, name="kokoro-warm", daemon=True)
    t.start()
    return t


def _serve_kokoro(handler) -> bool:
    from api.helpers import read_body

    raw = getattr(handler, "_json_body_bytes", None)
    try:
        data = json.loads(raw) if raw is not None else (read_body(handler) or {})
    except Exception:
        data = {}
    text = str(data.get("text") or "") if isinstance(data, dict) else ""
    try:
        body = kokoro_wav(text)
    except Exception as exc:  # engine missing or failed: the client falls back
        body, err = None, f"kokoro unavailable: {type(exc).__name__}"
    else:
        err = "text is required"
    if body is None:
        payload = json.dumps({"error": err}).encode("utf-8")
        handler.send_response(503 if err.startswith("kokoro") else 400)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    handler.send_response(200)
    handler.send_header("Content-Type", "audio/wav")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def agent_home_request(agent: dict) -> dict:
    """The gateway create-session body for an agent's one persistent home session.

    The id is derived here from the registry record (never from the client), so a
    click always lands in the same row: ``ensure_session`` is idempotent.
    """
    name = str(agent.get("name") or str(agent.get("id") or "").split(":")[-1])
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.lower())[:48] or "jaeger"
    lead = str(agent.get("role") or "") == "lead"
    title = "Jaeger" if lead else str(agent.get("display_name") or name)
    return {
        "session_id": f"agent-{safe}",
        "title": title,
        "source": "webui",
        "metadata": {"agent_id": str(agent.get("id")), "home": True, "source": "webui"},
    }


def _serve_agent_home(handler) -> bool:
    """POST /api/jaeger/agent-home {agent_id} -> the agent's home session."""
    import json as _json
    from urllib.parse import quote

    from api.helpers import bad, read_body

    try:
        body = read_body(handler) or {}
    except Exception:  # noqa: BLE001
        body = {}
    agent_id = str(body.get("agent_id") or "").strip()
    if not agent_id:
        return bad(handler, "agent_id required", 400)
    status, agent = _gateway_json("GET", f"/v1/agents/{quote(agent_id, safe='')}")
    if status != 200 or not isinstance(agent, dict) or not agent.get("id"):
        return bad(handler, "unknown agent", 404)
    raw = _json.dumps(agent_home_request(agent)).encode()
    return _proxy(handler, "POST", "/v1/sessions", raw)


def _gateway_json(method: str, path: str):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    import json as _json

    req = Request(f"{gateway_base()}{path}", method=method)
    req.add_header("Accept", "application/json")
    for key, value in client_headers("webui").items():
        req.add_header(key, value)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, _json.loads(resp.read() or b"{}")
    except HTTPError as exc:
        return exc.code, {}
    except Exception:  # noqa: BLE001
        return 502, {}


def route(handler, parsed, method: str) -> bool:
    """Return True if this request was handled (success or error response)."""
    path = parsed.path or ""
    method = (method or "GET").upper()

    # Sessions, the SSE stream and approvals live in the sibling overlay.
    # Chained here rather than patched into the vendored routes.py because
    # this function is ALREADY the mounted hook for both GET and POST — one
    # dispatch point, no extra patch to keep rebasing against upstream.
    try:
        from api.jaeger_sessions import route as _sessions_route
    except ImportError:  # pragma: no cover — overlay not installed
        _sessions_route = None
    if _sessions_route is not None:
        handled = _sessions_route(handler, parsed, method)
        if handled is not False:
            return True

    # Per-framework session index — each backend's own conversations, split by
    # where they were started. Served by the RUNNER, not the gateway.
    if method == "GET" and path in {"/api/profile-sessions", "/v1/profile-sessions"}:
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/profile-sessions{qs}", base=runner_base())

    if method == "GET" and path in {"/api/agents", "/v1/agents"}:
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/agents{qs}")

    if method == "GET" and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        if suffix and "/activate" not in suffix:
            return _proxy(handler, "GET", f"/v1/agents/{suffix}")
        return False

    if method == "POST" and path in {"/api/agents", "/v1/agents"}:
        raw = getattr(handler, "_json_body_bytes", None)
        if raw is None:
            from api.helpers import read_body

            raw = json.dumps(read_body(handler) or {}).encode("utf-8")
        return _proxy(handler, "POST", "/v1/agents", raw)

    if method == "POST" and path.endswith("/seen") and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        raw = getattr(handler, "_json_body_bytes", None)
        if raw is None:
            from api.helpers import read_body

            raw = json.dumps(read_body(handler) or {}).encode("utf-8")
        return _proxy(handler, "POST", f"/v1/agents/{suffix}", raw)

    if method == "POST" and path.endswith("/activate") and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        return _proxy(handler, "POST", f"/v1/agents/{suffix}")

    if method == "POST" and path.endswith("/handoff") and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        raw = getattr(handler, "_json_body_bytes", None)
        if raw is None:
            from api.helpers import read_body

            raw = json.dumps(read_body(handler) or {}).encode("utf-8")
        return _proxy(handler, "POST", f"/v1/agents/{suffix}", raw)

    # Speak-first feed: what Jaeger said on its own initiative, any session.
    if method == "GET" and path == "/api/jaeger/notifications":
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/notifications{qs}")

    # Jaeger's local voice for the companion (Kokoro, offline).
    if method == "GET" and path == "/api/jaeger/frameworks":
        qs = f"?{parsed.query}" if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/frameworks{qs}")
    if method == "POST" and path.startswith("/api/jaeger/frameworks/") and path.endswith("/grants"):
        from urllib.parse import quote
        fid = path[len("/api/jaeger/frameworks/"):-len("/grants")]
        if not fid or "/" in fid:
            from api.helpers import bad
            return bad(handler, "bad framework id", 400)
        import json as _json
        from api.helpers import read_body
        return _proxy(handler, "POST", f"/v1/frameworks/{quote(fid, safe='')}/grants",
                      _json.dumps(read_body(handler) or {}).encode())
    if method == "POST" and path == "/api/jaeger/agent-home":
        return _serve_agent_home(handler)
    if method == "POST" and path == "/api/jaeger/tts":
        return _serve_kokoro(handler)

    # The 3D avatar's model (a fixed local file; no path from the request).
    if method == "GET" and path == "/api/jaeger/avatar/model.vrm":
        return _serve_avatar_model(handler)

    # What Jaeger is doing now (jaeger.state), for the companion avatar.
    if method == "GET" and path == "/api/jaeger/presence":
        return _proxy(handler, "GET", "/v1/presence")

    # Connect Apps (Agents View panel). The install body is relayed as-is;
    # the Gateway enforces confirm:true and the owner-caller rule.
    if path == "/api/connect-apps" and method == "GET":
        return _proxy(handler, "GET", "/v1/connect-apps")
    if path.startswith("/api/connect-apps/"):
        rest = path[len("/api/connect-apps/"):].split("/")
        if len(rest) == 2 and rest[0]:
            from urllib.parse import quote

            app = quote(rest[0], safe="")
            if rest[1] == "state" and method == "GET":
                qs = f"?{parsed.query}" if parsed.query else ""
                return _proxy(handler, "GET", f"/v1/connect-apps/{app}/state{qs}")
            if rest[1] == "install" and method == "POST":
                raw = getattr(handler, "_json_body_bytes", None)
                if raw is None:
                    from api.helpers import read_body

                    raw = json.dumps(read_body(handler) or {}).encode("utf-8")
                return _proxy(handler, "POST", f"/v1/connect-apps/{app}/install", raw)

    if method == "GET" and path in {"/api/handoffs", "/v1/handoffs"}:
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/handoffs{qs}")

    # One handoff, or its exchange (task + specialist messages + summary).
    if method == "GET" and path.startswith("/api/handoffs/"):
        from urllib.parse import quote
        rest = path[len("/api/handoffs/"):].strip("/").split("/")
        if len(rest) == 1 and rest[0]:
            return _proxy(handler, "GET", f"/v1/handoffs/{quote(rest[0], safe='')}")
        if len(rest) == 2 and rest[0] and rest[1] == "messages":
            return _proxy(handler, "GET", f"/v1/handoffs/{quote(rest[0], safe='')}/messages")
        return False

    return False
