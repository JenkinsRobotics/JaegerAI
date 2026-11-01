"""Jaeger WebUI sign-in gate for remote (Tailscale) requests.

Loopback machine clients (JaegerShell, MCP hub, bridge, A2A, ARES worker, jobs,
agent tokens) keep working untouched: the gate only applies to requests that
arrive through the configured public URL (Tailscale Serve) or from a
non-loopback peer. Config lives in ``<state>/config/webui-auth.json``::

    {"webui": {"public_url": "https://host.ts.net:8443",
               "basic_auth": {"username": "...", "password_hash": "scrypt$...",
                              "secret": "<base64 >=32 bytes>"}}}

No plaintext password is ever stored. Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

COOKIE = "jaeger_webui_session"
SESSION_TTL = 30 * 86400
LOGIN_PATH = "/jaeger/login"
LOGOUT_PATH = "/jaeger/logout"
STATUS_PATHS = {"/api/auth/status", "/api/status", "/jaeger/auth/status"}
_PUBLIC = {LOGIN_PATH, "/health", "/favicon.ico"} | STATUS_PATHS
_FORWARD_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "Tailscale-User-Login", "Forwarded")
_LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1"}
MAX_FAILS = 5
FAIL_WINDOW = 15 * 60

_SCRYPT = (2 ** 15, 8, 1)


# ── password hashing ───────────────────────────────────────────────────────
def hash_password(password: str, *, salt: bytes | None = None) -> str:
    n, r, p = _SCRYPT
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)
    b = lambda x: base64.b64encode(x).decode()
    return f"scrypt${n}${r}${p}${b(salt)}${b(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


# ── config ─────────────────────────────────────────────────────────────────
def config_path() -> Path:
    override = os.getenv("JAEGER_WEBUI_AUTH_CONFIG")
    if override:
        return Path(override)
    state = os.getenv("JAEGER_STATE_HOME") or os.getenv("JAEGER_STATE_DIR") or str(Path.home() / ".jaeger")
    return Path(state) / "config" / "webui-auth.json"


_cache: dict = {"mtime": None, "cfg": None}


def load_config() -> dict | None:
    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _cache["mtime"] != mtime:
        try:
            data = json.loads(path.read_text())
            webui = data.get("webui") or {}
            ba = webui.get("basic_auth") or {}
            ok = all(isinstance(ba.get(k), str) and ba.get(k) for k in ("username", "password_hash", "secret"))
            cfg = {"username": ba["username"], "password_hash": ba["password_hash"],
                   "secret": ba["secret"].encode(), "public_url": str(webui.get("public_url") or "")} if ok else None
            if cfg and len(cfg["secret"]) < 32:
                cfg = None
        except Exception:
            cfg = None
        _cache.update(mtime=mtime, cfg=cfg)
    return _cache["cfg"]


def _public_host(cfg: dict) -> tuple[str, int | None]:
    u = urlparse(cfg.get("public_url") or "")
    return (u.hostname or "").lower(), u.port


# ── request classification ────────────────────────────────────────────────
def _hostname(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]")[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _is_loopback_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        return ip.is_loopback or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def host_allowed(handler, cfg: dict) -> bool:
    allowed = set(_LOOPBACK_NAMES) | {"host.docker.internal"}
    allowed |= {h.strip().lower() for h in os.getenv("JAEGER_WEBUI_ALLOWED_HOSTS", "").split(",") if h.strip()}
    ph, _ = _public_host(cfg)
    if ph:
        allowed.add(ph)
    for header in ("Host", "X-Forwarded-Host"):
        raw = handler.headers.get(header)
        if header == "Host" and not raw:
            return False
        if raw and _hostname(raw.split(",")[0]) not in allowed:
            return False
    return True


def is_remote(handler, cfg: dict) -> bool:
    if not _is_loopback_ip(str(handler.client_address[0])):
        return True
    if any(handler.headers.get(h) for h in _FORWARD_HEADERS):
        return True
    ph, _ = _public_host(cfg)
    return bool(ph) and _hostname(handler.headers.get("Host", "")) == ph


def client_key(handler) -> str:
    fwd = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or str(handler.client_address[0])


# ── sessions ──────────────────────────────────────────────────────────────
def issue_session(cfg: dict, now: float | None = None) -> str:
    exp = int((now or time.time()) + SESSION_TTL)
    payload = base64.urlsafe_b64encode(json.dumps({"u": cfg["username"], "e": exp, "n": secrets.token_hex(8)}).encode()).decode().rstrip("=")
    sig = hmac.new(cfg["secret"], payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session(cfg: dict, value: str | None, now: float | None = None) -> bool:
    if not value or "." not in value:
        return False
    payload, sig = value.rsplit(".", 1)
    good = hmac.new(cfg["secret"], payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data.get("u") == cfg["username"] and int(data["e"]) > (now or time.time())
    except Exception:
        return False


def _cookie(handler) -> str | None:
    raw = handler.headers.get("Cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def _secure(handler, cfg: dict) -> bool:
    return cfg.get("public_url", "").startswith("https://") or handler.headers.get("X-Forwarded-Proto") == "https"


def _cookie_header(handler, cfg: dict, value: str, max_age: int) -> str:
    flags = "; Secure" if _secure(handler, cfg) else ""
    return f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{flags}"


# ── rate limiting ─────────────────────────────────────────────────────────
_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()


def rate_limited(key: str, now: float | None = None) -> bool:
    now = now or time.time()
    with _fails_lock:
        recent = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
        _fails[key] = recent
        return len(recent) >= MAX_FAILS


def record_failure(key: str, now: float | None = None) -> None:
    with _fails_lock:
        _fails.setdefault(key, []).append(now or time.time())


def clear_failures(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)


# ── responses ─────────────────────────────────────────────────────────────
def _send(handler, status: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def _json(handler, status: int, value: dict, headers: dict | None = None) -> None:
    _send(handler, status, json.dumps(value).encode(), "application/json", headers)


def _safe_next(raw: str | None) -> str:
    raw = (raw or "/").strip()
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw or raw.startswith(LOGIN_PATH):
        return "/"
    return raw


def login_html(next_path: str = "/", error: str = "") -> bytes:
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return (_LOGIN_TEMPLATE
            .replace("{{NEXT}}", html.escape(next_path, quote=True))
            .replace("{{ERROR}}", err)).encode()


def _mark_consumed(handler) -> None:
    """Tell the keep-alive body drain this request's body is already read."""
    try:
        from api.helpers import mark_request_body_consumed
        mark_request_body_consumed(handler)
    except Exception:
        pass


def _handle_login_post(handler, cfg: dict) -> None:
    key = client_key(handler)
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > 4096:
        return _json(handler, 413, {"error": "too large"})
    form = parse_qs(handler.rfile.read(length).decode("utf-8", "replace"))
    _mark_consumed(handler)
    nxt = _safe_next((form.get("next") or ["/"])[0])
    if rate_limited(key):
        return _send(handler, 429, login_html(nxt, "Too many attempts. Try again in 15 minutes."),
                     "text/html; charset=utf-8", {"Retry-After": str(FAIL_WINDOW)})
    user = (form.get("username") or [""])[0]
    pw = (form.get("password") or [""])[0]
    if hmac.compare_digest(user.encode(), cfg["username"].encode()) & verify_password(pw, cfg["password_hash"]):
        clear_failures(key)
        handler.send_response(303)
        handler.send_header("Location", nxt)
        handler.send_header("Set-Cookie", _cookie_header(handler, cfg, issue_session(cfg), SESSION_TTL))
        handler.send_header("Content-Length", "0")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        return None
    record_failure(key)
    return _send(handler, 401, login_html(nxt, "Wrong username or password."), "text/html; charset=utf-8")


def gate(handler, parsed) -> bool:
    """Return True to continue normal routing; False when the gate already responded."""
    cfg = load_config()
    if cfg is None:
        return True
    if not host_allowed(handler, cfg):
        _json(handler, 400, {"error": "Invalid Host header"})
        return False
    if not is_remote(handler, cfg):
        return True  # loopback machine clients and JaegerShell
    path = parsed.path
    authed = verify_session(cfg, _cookie(handler))
    if path in STATUS_PATHS and handler.command == "GET":
        _json(handler, 200, {"ok": True, "auth_required": True, "auth_providers": ["basic"],
                             "authenticated": authed, "login_url": LOGIN_PATH})
        return False
    if path == LOGIN_PATH:
        if handler.command == "POST":
            _handle_login_post(handler, cfg)
        else:
            nxt = _safe_next((parse_qs(parsed.query).get("next") or ["/"])[0])
            if authed:
                handler.send_response(303); handler.send_header("Location", nxt)
                handler.send_header("Content-Length", "0"); handler.end_headers()
            else:
                _send(handler, 200, login_html(nxt), "text/html; charset=utf-8")
        return False
    if path == LOGOUT_PATH:
        handler.send_response(303)
        handler.send_header("Location", LOGIN_PATH)
        handler.send_header("Set-Cookie", _cookie_header(handler, cfg, "", 0))
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return False
    if authed or path == "/health":
        return True
    if path.startswith("/api/") or path.startswith("/v1/") or handler.command != "GET":
        _json(handler, 401, {"error": "Authentication required", "auth_providers": ["basic"], "login_url": LOGIN_PATH})
    else:
        target = path + ("?" + parsed.query if parsed.query else "")
        handler.send_response(302)
        handler.send_header("Location", f"{LOGIN_PATH}?next={quote(target, safe='/')}")
        handler.send_header("Content-Length", "0")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
    return False


_LOGIN_TEMPLATE = """<!doctype html><html lang="en" data-layout="glass"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="color-scheme" content="dark light">
<title>Sign in · Jaeger</title>
<script>try{var p=localStorage.getItem('appearance.layout');if(p&&/^(glass|arc|linear|dia)$/.test(JSON.parse(p)||p))document.documentElement.dataset.layout=JSON.parse(p)||p}catch(e){try{var q=localStorage.getItem('appearance.layout');if(/^(glass|arc|linear|dia)$/.test(q))document.documentElement.dataset.layout=q}catch(_){}}</script>
<style>
:root{--bg:#0b0d12;--bg2:#1a2030;--card:rgba(255,255,255,.07);--line:rgba(255,255,255,.14);--fg:#f2f4f8;--mut:#a7afbf;--acc:#5aa2ff;--accfg:#04122a;--r:22px;--blur:28px;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif}
[data-layout=arc]{--bg:#141019;--bg2:#3a2457;--acc:#c79bff;--accfg:#1d0b33;--r:18px}
[data-layout=linear]{--bg:#08090a;--bg2:#08090a;--card:#111214;--line:#23252a;--acc:#7c83ff;--accfg:#fff;--r:10px;--blur:0px}
[data-layout=dia]{--bg:#f6f1ea;--bg2:#efe4d4;--card:#fffdf9;--line:#e3d8c8;--fg:#2a2420;--mut:#6b6058;--acc:#b4532a;--accfg:#fff;--r:16px;--blur:0px}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:radial-gradient(120% 80% at 50% 0%,var(--bg2),var(--bg));color:var(--fg);display:grid;place-items:center;padding:max(24px,env(safe-area-inset-top)) 20px max(24px,env(safe-area-inset-bottom))}
main{width:min(380px,100%);background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:32px 26px;backdrop-filter:blur(var(--blur)) saturate(160%);-webkit-backdrop-filter:blur(var(--blur)) saturate(160%);box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{width:52px;height:52px;border-radius:14px;background:linear-gradient(135deg,var(--acc),color-mix(in srgb,var(--acc) 40%,#000));display:grid;place-items:center;font-weight:700;font-size:24px;color:var(--accfg);margin-bottom:18px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}p.sub{margin:0 0 24px;color:var(--mut);font-size:15px}
label{display:block;font-size:13px;color:var(--mut);margin:14px 0 6px}
input{width:100%;font:inherit;font-size:17px;padding:13px 14px;border-radius:calc(var(--r)/2);border:1px solid var(--line);background:color-mix(in srgb,var(--fg) 6%,transparent);color:var(--fg);outline:none}
input:focus{border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 35%,transparent)}
button{margin-top:22px;width:100%;font:inherit;font-size:17px;font-weight:600;padding:14px;border:0;border-radius:calc(var(--r)/2);background:var(--acc);color:var(--accfg);cursor:pointer}
.err{background:color-mix(in srgb,#ff4d4f 16%,transparent);color:#ffb3b3;border-radius:10px;padding:10px 12px;font-size:14px;margin:0 0 8px}
[data-layout=dia] .err{color:#8a1f1f}
.foot{margin-top:18px;font-size:12px;color:var(--mut);text-align:center}
</style></head><body><main>
<div class="logo" aria-hidden="true">J</div><h1>Sign in to Jaeger</h1><p class="sub">Private access over your tailnet</p>
{{ERROR}}
<form method="post" action="/jaeger/login" autocomplete="on">
<input type="hidden" name="next" value="{{NEXT}}">
<label for="u">Username</label><input id="u" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required>
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form>
<p class="foot">Jaeger AI · signed, HttpOnly session</p></main></body></html>"""
