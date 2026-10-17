"""Text-To-Speech (TTS) API route and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
Supports Edge TTS, ElevenLabs, and OpenAI-compatible engines with SSRF protection,
IP pinning, prosody normalization, and per-client rate limiting.
"""
from __future__ import annotations

import errno
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket as _socket
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

from .config import get_config
from .helpers import bad, read_body

logger = logging.getLogger("hermes.webui")

_TTS_PROXY_MAX_BYTES = 16 * 1024 * 1024
_TTS_LOCALHOST_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _normalize_tts_prosody(value: Any, *, unit: str) -> str | None:
    if not value:
        return ""
    value = str(value).strip()
    if not re.fullmatch(r"[+-]?\d{1,3}" + re.escape(unit), value):
        return None
    amount = int(value[: -len(unit)])
    if -100 <= amount <= 100:
        return value
    return None


def _tts_addr_is_blocked(ip_str: str) -> bool:
    """Return True when IP is in a private or otherwise non-routable class.

    The explicit flags below document the concrete SSRF-risk classes, but the
    load-bearing rule is the ``not is_global`` backstop: it blocks every address
    that is not globally routable — including ranges the named flags miss, most
    notably ``100.64.0.0/10`` (RFC 6598 CGNAT, also Tailscale's default address
    space), the ``198.18.0.0/15`` benchmarking range, and any future
    non-global allocation — so a rebinding host cannot reach a victim's tailnet
    or carrier-NAT peer.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _tts_host_is_blocked_target(hostname: str) -> bool:
    """True if the hostname resolves to (or literally is) a private / loopback /
    link-local / reserved / multicast address — the SSRF-risk targets that an
    OpenAI-compatible TTS base_url must not be allowed to reach. Public hosts
    (a user's own hosted OpenAI-compatible server) are allowed; the explicit
    localhost-over-http dev case is handled separately by the caller."""
    host = (hostname or "").strip().lower()
    if not host:
        return True

    try:
        ipaddress.ip_address(host)
        return _tts_addr_is_blocked(host)
    except ValueError:
        pass

    try:
        infos = _socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        sockaddr = info[4]
        if sockaddr and _tts_addr_is_blocked(str(sockaddr[0])):
            return True
    return False


def _tts_resolve_pinned_addresses(hostname: str, port: int | None) -> list[str]:
    """Resolve once, validate the RRset, and preserve candidate dial order."""
    host = (hostname or "").strip().lower()
    if not host:
        raise ValueError("invalid OpenAI TTS base_url host")

    try:
        infos = _socket.getaddrinfo(host, port, type=_socket.SOCK_STREAM)
    except Exception as exc:
        raise ValueError("could not resolve OpenAI TTS base_url host") from exc
    pinned_hosts = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        pinned_host = str(sockaddr[0])
        if _tts_addr_is_blocked(pinned_host):
            raise ValueError("resolved OpenAI TTS target is not allowed")
        pinned_hosts.append(pinned_host)
    if not pinned_hosts:
        raise ValueError("could not resolve OpenAI TTS base_url host")
    return pinned_hosts


def _tts_resolve_pinned_address(hostname: str) -> str:
    """Return the first vetted literal address for direct helper callers."""
    return _tts_resolve_pinned_addresses(hostname, None)[0]


def _normalized_openai_tts_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip()
    parsed = urlsplit(raw)
    hostname = (parsed.hostname or "").strip().lower()
    if parsed.username or parsed.password:
        raise ValueError("invalid OpenAI base_url in config")
    if not parsed.scheme or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("invalid OpenAI base_url in config")
    if parsed.scheme == "https":
        if _tts_host_is_blocked_target(hostname):
            raise ValueError("invalid OpenAI base_url in config")
    elif parsed.scheme == "http" and hostname in _TTS_LOCALHOST_HOSTS:
        pass
    else:
        raise ValueError("invalid OpenAI base_url in config")
    path = parsed.path.rstrip("/") or ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _buffer_tts_audio_response(resp: Any, *, max_bytes: int | None = None) -> bytes:
    if max_bytes is None:
        max_bytes = _TTS_PROXY_MAX_BYTES
    headers = getattr(resp, "headers", None)
    content_type = ""
    if headers is not None:
        try:
            content_type = str(headers.get("Content-Type") or "")
        except Exception:
            content_type = ""
    if not content_type:
        try:
            info = resp.info()
            content_type = str(info.get("Content-Type") or "")
        except Exception:
            content_type = ""
    if content_type and not content_type.lower().startswith("audio/"):
        raise ValueError("upstream returned non-audio content")
    audio_data = bytearray()
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        audio_data.extend(chunk)
        if len(audio_data) > max_bytes:
            raise ValueError("upstream audio exceeded byte limit")
    return bytes(audio_data)


class _NoRedirectTtsHandler(HTTPRedirectHandler):
    """Refuse to follow redirects on the TTS call."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        raise ValueError("OpenAI TTS upstream attempted a redirect")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a pinned IP while keeping Host and TLS SNI on the hostname."""

    def connect(self) -> None:
        sys.audit("http.client.connect", self, self.host, self.port)
        last_error = None
        for pinned_host in _tts_resolve_pinned_addresses(self.host, self.port):
            try:
                self.sock = _socket.create_connection(
                    (pinned_host, self.port), self.timeout, self.source_address
                )
                break
            except OSError as exc:
                last_error = exc
        else:
            if last_error is not None:
                raise last_error
            raise OSError("could not connect to any pinned OpenAI TTS target")
        try:
            self.sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise

        if self._tunnel_host:
            self._tunnel()

        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedHTTPSHandler(HTTPSHandler):
    def https_open(self, req: Any) -> Any:
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


def _tts_open(req: Any, *, timeout: int = 30, opener_factory: Any = None) -> Any:
    """Thin network seam for the TTS upstream fetch so tests can intercept it."""
    if opener_factory is not None:
        opener = opener_factory()
        return opener.open(req, timeout=timeout)
    return urlopen(req, timeout=timeout)


class _TtsRateLimiter:
    def __init__(self, window_seconds: float = 2.0, prune_interval: int = 50) -> None:
        self.window = window_seconds
        self.prune_interval = prune_interval
        self._hits: dict[str, float] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def _get_client_key(self, h: Any) -> str:
        trust_proxy = os.getenv("HERMES_WEBUI_TRUST_FORWARDED_FOR", "").strip().lower()
        if trust_proxy in ("1", "true", "yes", "on"):
            for hdr in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
                val = h.headers.get(hdr)
                if val:
                    ip = val.split(",")[0].strip().split(";")[0].strip()
                    if ip:
                        return ip
        return getattr(h, "client_address", ("unknown",))[0]

    def check(self, handler: Any, session_cookie: Any = None) -> bool:
        key = self._get_client_key(handler)
        if session_cookie and "." in str(session_cookie):
            key = str(session_cookie).split(".", 1)[0]
        now = time.time()
        with self._lock:
            self._checks += 1
            if self._checks % self.prune_interval == 0:
                cutoff = now - (self.window * 10)
                self._hits = {k: v for k, v in self._hits.items() if v > cutoff}
            last = self._hits.get(key, 0)
            if now - last < self.window:
                return False
            self._hits[key] = now
            return True


_GLOBAL_TTS_LIMITER = _TtsRateLimiter(window_seconds=2.0)


def handle_tts(handler: Any, parsed: Any) -> bool:
    """Generate TTS audio via supported server TTS engines. POST JSON body only."""
    text = ""
    voice = "zh-CN-XiaoxiaoNeural"
    rate_str = ""
    pitch_str = ""
    engine = "edge"  # "edge" | "elevenlabs" | "openai" | "browser"

    if handler.command != "POST":
        return bad(handler, "POST required for /api/tts", 405)

    try:
        data = read_body(handler)
        text = (data.get("text") or "").strip()
        voice = data.get("voice") or voice
        rate_str = _normalize_tts_prosody(data.get("rate"), unit="%")
        pitch_str = _normalize_tts_prosody(data.get("pitch"), unit="Hz")
        engine = (data.get("engine") or "edge").strip().lower()
    except Exception:
        return bad(handler, "invalid request body", 400)

    if rate_str is None:
        return bad(handler, "invalid rate", 400)
    if pitch_str is None:
        return bad(handler, "invalid pitch", 400)

    if not text:
        return bad(handler, "text is required", 400)
    if len(text) > 5000:
        return bad(handler, "text too long (max 5000 characters)", 400)

    try:
        from api.auth import is_auth_enabled, parse_cookie, verify_session
    except Exception:
        from .auth import is_auth_enabled, parse_cookie, verify_session

    cv = None
    if is_auth_enabled():
        cv = parse_cookie(handler)
        if not (cv and verify_session(cv)):
            return bad(handler, "unauthorized", 401)

    limiter = getattr(handle_tts, "_tts_limiter", _GLOBAL_TTS_LIMITER)
    if not limiter.check(handler, cv):
        logger.warning("TTS rate limit hit for client=%s", limiter._get_client_key(handler))
        return bad(handler, "rate limit exceeded — please wait", 429)

    # ── ElevenLabs TTS ──────────────────────────────────────────────────
    if engine == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            try:
                from api.onboarding import _load_env_file
                from api.profiles import get_active_hermes_home
                api_key = _load_env_file(get_active_hermes_home() / ".env").get("ELEVENLABS_API_KEY", "")
            except Exception:
                pass
        if not api_key:
            return bad(handler, "ELEVENLABS_API_KEY not configured", 503)

        voice_id = "pNInz6obpgDQGcFmaJgB"
        model_id = "eleven_multilingual_v2"
        try:
            tts_cfg = (get_config() or {}).get("tts", {})
            if isinstance(tts_cfg, dict):
                el_cfg = tts_cfg.get("elevenlabs", {})
                if isinstance(el_cfg, dict):
                    voice_id = el_cfg.get("voice_id", voice_id)
                    model_id = el_cfg.get("model", model_id) or el_cfg.get("model_id", model_id)
        except Exception:
            pass

        if not re.fullmatch(r'[A-Za-z0-9_-]+', voice_id):
            return bad(handler, "invalid voice_id in config", 400)

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format=mp3_44100_128"
        req_body = json.dumps({
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode("utf-8")

        req = Request(url, data=req_body, headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        })

        try:
            with _tts_open(req, timeout=30, opener_factory=lambda: build_opener(ProxyHandler({}), _NoRedirectTtsHandler())) as resp:
                audio_data = _buffer_tts_audio_response(resp)
        except ValueError:
            logger.warning("ElevenLabs TTS rejected an invalid upstream response", exc_info=True)
            return bad(handler, "ElevenLabs TTS generation failed", 502)
        except Exception:
            logger.exception("ElevenLabs TTS generation failed")
            return bad(handler, "ElevenLabs TTS generation failed", 500)

        handler.send_response(200)
        handler.send_header("Content-Type", "audio/mpeg")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(audio_data)))
        handler.end_headers()
        try:
            handler.wfile.write(audio_data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    # ── OpenAI-compatible TTS ──────────────────────────────────────────
    if engine == "openai":
        api_key = os.getenv("VOICE_TOOLS_OPENAI_KEY", "").strip()
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            try:
                from api.onboarding import _load_env_file
                from api.profiles import get_active_hermes_home
                env_cfg = _load_env_file(get_active_hermes_home() / ".env")
                api_key = env_cfg.get("VOICE_TOOLS_OPENAI_KEY", "") or env_cfg.get("OPENAI_API_KEY", "")
            except Exception:
                pass
        if not api_key:
            return bad(handler, "OpenAI API key not configured", 503)

        base_url = urlunsplit(("https", "api.openai.com", "/v1", "", ""))
        model = "gpt-4o-mini-tts"
        oai_voice = "alloy"
        try:
            tts_cfg = (get_config() or {}).get("tts", {})
            if isinstance(tts_cfg, dict):
                oai_cfg = tts_cfg.get("openai", {})
                if isinstance(oai_cfg, dict):
                    base_url = _normalized_openai_tts_base_url(oai_cfg.get("base_url") or base_url)
                    model = oai_cfg.get("model") or model
                    oai_voice = oai_cfg.get("voice") or oai_voice
                else:
                    base_url = _normalized_openai_tts_base_url(base_url)
            else:
                base_url = _normalized_openai_tts_base_url(base_url)
        except ValueError:
            return bad(handler, "invalid OpenAI base_url in config", 400)
        except Exception:
            pass

        url = f"{base_url}/audio/speech"
        req_body = json.dumps({
            "model": model,
            "input": text,
            "voice": oai_voice,
        }).encode("utf-8")

        req = Request(url, data=req_body, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        })

        try:
            with _tts_open(req, timeout=30, opener_factory=lambda: build_opener(ProxyHandler({}), _NoRedirectTtsHandler(), _PinnedHTTPSHandler())) as resp:
                audio_data = _buffer_tts_audio_response(resp)
        except ValueError:
            logger.warning("OpenAI TTS rejected an invalid upstream response", exc_info=True)
            return bad(handler, "OpenAI TTS generation failed", 502)
        except Exception:
            logger.exception("OpenAI TTS generation failed")
            return bad(handler, "OpenAI TTS generation failed", 500)

        handler.send_response(200)
        handler.send_header("Content-Type", "audio/mpeg")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(audio_data)))
        handler.end_headers()
        try:
            handler.wfile.write(audio_data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    # ── Edge TTS ────────────────────────────────────────────────────────
    allowed = {
        "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural",
        "zh-CN-YunjianNeural", "zh-CN-YunyangNeural",
        "en-US-AriaNeural", "en-US-GuyNeural",
        "fr-CA-AntoineNeural", "fr-CA-JeanNeural",
        "fr-CA-SylvieNeural", "fr-CA-ThierryNeural",
        "fr-FR-DeniseNeural", "fr-FR-EloiseNeural", "fr-FR-HenriNeural",
        "id-ID-GadisNeural",
    }
    if voice not in allowed:
        return bad(handler, "invalid voice", 400)

    try:
        try:
            import edge_tts
        except ImportError:
            return bad(handler, "Edge TTS engine not installed on the server. Install it with: pip install edge-tts", 503)

        kwargs: dict[str, Any] = {}
        if rate_str:
            kwargs["rate"] = rate_str
        if pitch_str:
            kwargs["pitch"] = pitch_str

        comm = edge_tts.Communicate(text, voice, **kwargs)

        audio_buf = bytearray()
        for chunk in comm.stream_sync():
            if chunk.get("type") == "audio" and chunk.get("data"):
                audio_buf.extend(chunk["data"])

        if not audio_buf:
            return bad(handler, "TTS produced no audio", 500)

        handler.send_response(200)
        handler.send_header("Content-Type", "audio/mpeg")
        handler.send_header("Content-Length", str(len(audio_buf)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        try:
            handler.wfile.write(audio_buf)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    except BrokenPipeError:
        return True
    except Exception:
        logger.exception("Edge TTS generation failed")
        return bad(handler, "TTS generation failed", 500)

