"""Operator remote-access control plane: Tailscale Serve + WebUI auth.

The phone talks to the authenticated WebUI over Tailscale HTTPS.
Gateway, Bridge, and MCP stay on loopback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jaeger_ai.features.remote_access import store
from jaeger_ai.features.remote_access.policy import RemoteAccessPolicy

WEBUI_LOOPBACK_PORT = 8790
GATEWAY_PORT = 8810
HTTPS_PORT = 8443
PAIR_TTL_S = 15 * 60


def _tailscale_bin() -> str | None:
    return shutil.which("tailscale")


def tailscale_status() -> dict[str, Any]:
    binary = _tailscale_bin()
    if not binary:
        return {"ok": False, "installed": False, "error": "tailscale CLI is not installed"}
    try:
        proc = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "installed": True, "error": str(exc)}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "tailscale status failed").strip()
        needs_login = "logged out" in err.lower() or "not logged in" in err.lower()
        return {
            "ok": False,
            "installed": True,
            "logged_in": False,
            "needs_human": needs_login or "login" in err.lower(),
            "error": err[:400],
        }
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    self = payload.get("Self") or {}
    dns = str(self.get("DNSName") or "").rstrip(".")
    ips = [str(i) for i in (self.get("TailscaleIPs") or []) if ":" not in str(i)]
    return {
        "ok": True,
        "installed": True,
        "logged_in": True,
        "dns_name": dns,
        "ipv4": ips[0] if ips else None,
        "online": bool(self.get("Online", True)),
        "backend": payload.get("BackendState"),
    }


def _serve_https(target: str, port: int = HTTPS_PORT) -> dict[str, Any]:
    binary = _tailscale_bin()
    if not binary:
        return {"ok": False, "error": "tailscale CLI is not installed"}
    try:
        proc = subprocess.run(
            [binary, "serve", "--bg", f"--https={port}", target],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": (proc.stdout or proc.stderr or "").strip(),
        "target": target,
        "https_port": port,
    }


def _serve_off(port: int = HTTPS_PORT) -> dict[str, Any]:
    binary = _tailscale_bin()
    if not binary:
        return {"ok": True, "skipped": True}
    try:
        proc = subprocess.run(
            [binary, "serve", "--https", str(port), "off"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "").strip()}


def serve_status() -> dict[str, Any]:
    binary = _tailscale_bin()
    if not binary:
        return {"ok": False, "error": "tailscale not installed"}
    try:
        proc = subprocess.run(
            [binary, "serve", "status"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    text = (proc.stdout or proc.stderr or "").strip()
    funnel = "funnel" in text.lower() and "tailnet only" not in text.lower()
    https_urls = re.findall(r"https://[^\s]+", text)
    return {
        "ok": proc.returncode == 0,
        "text": text[:2000],
        "https_urls": https_urls,
        "funnel": funnel,
    }


def _listener(port: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"port": port, "listening": False}
    lines = [ln for ln in (proc.stdout or "").splitlines()[1:] if ln.strip()]
    binds = []
    for line in lines:
        if "(LISTEN)" in line:
            name = line.rsplit("(LISTEN)", 1)[0].split()[-1]
        else:
            parts = line.split()
            name = parts[-1] if parts else ""
        if name:
            binds.append(name)
    loopback_only = bool(binds) and all(
        addr.startswith("127.0.0.1:") or addr.startswith("[::1]:") for addr in binds
    )
    return {
        "port": port,
        "listening": bool(binds),
        "binds": binds,
        "loopback_only": loopback_only,
        "all_interfaces": any(b.startswith("*:") or b.startswith("0.0.0.0:") for b in binds),
    }


def _http_ok(url: str, *, timeout: float = 4.0, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "jaeger-remote-doctor"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(4000)
            return {"ok": 200 <= resp.status < 400, "status": resp.status, "body": body[:500]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def phone_url(state: dict[str, Any] | None = None) -> str:
    data = state or store.load()
    ts = tailscale_status()
    dns = str(ts.get("dns_name") or data.get("dns_name") or "").rstrip(".")
    port = int(data.get("https_port") or HTTPS_PORT)
    if dns:
        if port in (443, 8443):
            origin = f"https://{dns}:{port}" if port != 443 else f"https://{dns}"
            if port == 8443:
                origin = f"https://{dns}:8443"
            return origin
        return f"https://{dns}:{port}"
    return f"http://127.0.0.1:{WEBUI_LOOPBACK_PORT}"


def issue_pairing_token(*, ttl_s: int = PAIR_TTL_S) -> dict[str, Any]:
    raw = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    state = store.load()
    pending = [p for p in (state.get("pairing") or []) if int(p.get("exp") or 0) > time.time() and not p.get("used")]
    pending.append({"hash": digest, "exp": int(time.time()) + int(ttl_s), "used": False})
    state["pairing"] = pending[-8:]
    store.save(state)
    origin = phone_url(state)
    return {
        "token": raw,
        "expires_in_s": ttl_s,
        "url": f"{origin}/login?pair={quote(raw, safe='')}",
    }


def consume_pairing_token(token: str) -> bool:
    digest = hashlib.sha256(str(token or "").encode()).hexdigest()
    state = store.load()
    now = time.time()
    found = False
    kept = []
    for item in state.get("pairing") or []:
        if item.get("used") or int(item.get("exp") or 0) <= now:
            continue
        if not found and item.get("hash") == digest:
            found = True
            continue
        kept.append(item)
    if found:
        state["pairing"] = kept
        store.save(state)
    return found


def policy_from_store() -> RemoteAccessPolicy:
    state = store.load()
    token = str(state.get("token") or os.environ.get("JAEGER_REMOTE_ACCESS_TOKEN") or "").strip()
    enabled = bool(state.get("enabled"))
    return RemoteAccessPolicy(token=token, remote_enabled=enabled)


def _ensure_webui_password() -> dict[str, Any]:
    """Ensure the WebUI process will require a password.

    The running WebUI caches password hashes in-process, so enable restarts
    WebUI with HERMES_WEBUI_PASSWORD in its environment. Plaintext is returned
    only when this call generated a new password.
    """
    existing = os.environ.get("HERMES_WEBUI_PASSWORD", "").strip()
    if existing:
        return {"configured": True, "generated": False}
    password = secrets.token_urlsafe(18)
    os.environ["HERMES_WEBUI_PASSWORD"] = password
    return {"configured": True, "generated": True, "password": password}


def enable(*, https_port: int = HTTPS_PORT, start_webui: bool = True, serve: bool = True) -> dict[str, Any]:
    ts = tailscale_status()
    if not ts.get("installed"):
        return {
            "ok": False,
            "needs_human": True,
            "error": "Install Tailscale on this Mac, then run `jaeger remote enable` again.",
            "tailscale": ts,
        }
    if not ts.get("logged_in"):
        return {
            "ok": False,
            "needs_human": True,
            "error": "Log into Tailscale on this Mac (`tailscale up`), then run `jaeger remote enable` again.",
            "tailscale": ts,
        }
    token = store.ensure_token()
    password = {"configured": False, "generated": False}
    if start_webui:
        password = _ensure_webui_password()
    os.environ["JAEGER_WEBUI_HOST"] = "127.0.0.1"
    os.environ["HERMES_WEBUI_SECURE"] = "1"
    os.environ["HERMES_WEBUI_TRUST_FORWARDED_PROTO"] = "1"
    os.environ["HERMES_WEBUI_PASSKEY"] = "1"
    webui = {"ok": True, "skipped": True}
    if start_webui:
        from jaeger_ai.features.webui.service.service import WebUIService
        svc = WebUIService()
        try:
            svc.stop()
        except Exception:
            pass
        os.environ["JAEGER_WEBUI_HOST"] = "127.0.0.1"
        webui = svc.start(publish_tailscale=False)
    serve_res = {"ok": True, "skipped": True}
    if serve:
        serve_res = _serve_https(f"http://127.0.0.1:{WEBUI_LOOPBACK_PORT}", https_port)
    pair = issue_pairing_token()
    state = store.load()
    state.update({
        "enabled": True,
        "token": token,
        "https_port": https_port,
        "webui_port": WEBUI_LOOPBACK_PORT,
        "webui_host": "127.0.0.1",
        "dns_name": ts.get("dns_name"),
        "tailscale_ipv4": ts.get("ipv4"),
        "serve": bool(serve_res.get("ok")),
    })
    store.save(state)
    origin = phone_url(state)
    return {
        "ok": bool(webui.get("ok")) and (bool(serve_res.get("ok")) if serve else True),
        "enabled": True,
        "origin": origin,
        "pair_url": pair["url"],
        "pair_expires_in_s": pair["expires_in_s"],
        "password_generated": bool(password.get("generated")),
        "password": password.get("password"),
        "webui": webui,
        "serve": serve_res,
        "tailscale": ts,
        "trust_boundary": (
            "Tailscale Serve terminates HTTPS and proxies to loopback WebUI. "
            "The WebUI process sees 127.0.0.1 as the TCP peer. "
            "Enforceable boundary: tailnet membership + WebUI authentication."
        ),
    }


def disable(*, stop_serve: bool = True) -> dict[str, Any]:
    state = store.load()
    state["enabled"] = False
    store.save(state)
    serve_res = _serve_off(int(state.get("https_port") or HTTPS_PORT)) if stop_serve else {"ok": True, "skipped": True}
    return {"ok": True, "enabled": False, "serve": serve_res}


def doctor() -> dict[str, Any]:
    state = store.load()
    ts = tailscale_status()
    serve = serve_status()
    gw = _listener(GATEWAY_PORT)
    webui = _listener(WEBUI_LOOPBACK_PORT)
    adapter = _listener(8791)
    mcp = _listener(8792)
    origin = phone_url(state)
    https = _http_ok(origin + "/") if origin.startswith("https://") else {"ok": False, "error": "no https origin"}
    auth = _http_ok(origin + "/api/auth/status") if origin.startswith("https://") else _http_ok("http://127.0.0.1:8790/api/auth/status")
    sessions = _http_ok(origin + "/api/jaeger/sessions") if origin.startswith("https://") else _http_ok("http://127.0.0.1:8790/api/jaeger/sessions")
    auth_body = {}
    try:
        auth_body = json.loads((auth.get("body") or b"{}").decode("utf-8", "replace"))
    except Exception:
        pass
    gateway_private = (not gw.get("all_interfaces")) and (gw.get("loopback_only") or not gw.get("listening"))
    public_exposure = bool(webui.get("all_interfaces")) or bool(serve.get("funnel"))
    entity_id = ""
    try:
        gw_status = _http_ok("http://127.0.0.1:8810/v1/runtime/status")
        payload = json.loads((gw_status.get("body") or b"{}").decode("utf-8", "replace"))
        entity_id = str(((payload.get("Agent") or {}).get("entity_id")) or "")
    except Exception:
        try:
            from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
            ident_path = InstanceLayout(root=resolve_instance_dir()).entity_identity_path
            if ident_path.is_file():
                entity_id = str(json.loads(ident_path.read_text(encoding="utf-8")).get("entity_id") or "")
        except Exception:
            pass
    auth_healthy = bool(auth_body.get("auth_enabled"))
    sessions_denied = int(sessions.get("status") or 0) in {401, 403} or (
        auth_healthy and not sessions.get("ok")
    )
    if not auth_healthy:
        sessions_denied = False
    checks = {
        "tailscale": bool(ts.get("ok")),
        "https": bool(https.get("ok") or (https.get("status") in {401, 403, 200})),
        "authentication": auth_healthy,
        "unauthenticated_sessions_denied": bool(sessions_denied) if auth_healthy else False,
        "webui_listening": bool(webui.get("listening")),
        "gateway_private": gateway_private,
        "adapter_loopback": bool(adapter.get("loopback_only") or not adapter.get("listening")),
        "mcp_loopback": bool(mcp.get("loopback_only") or not mcp.get("listening")),
        "funnel_off": not bool(serve.get("funnel")),
        "enabled": bool(state.get("enabled")),
    }
    return {
        "ok": all(checks[k] for k in (
            "tailscale", "https", "gateway_private", "funnel_off",
        )) and bool(state.get("enabled")),
        "checks": checks,
        "entity_id": entity_id,
        "origin": origin,
        "tailscale": ts,
        "serve": serve,
        "gateway": gw,
        "webui": webui,
        "auth_status": auth_body,
        "trust_boundary": (
            "Tailscale Serve proxies to loopback. Source-IP at the WebUI is loopback. "
            "Outer boundary is tailnet membership plus WebUI login/passkey/session."
        ),
    }


def status_report() -> dict[str, Any]:
    doc = doctor()
    state = store.load()
    phones = 0
    try:
        from jaeger_ai.features.webui.api import auth as webui_auth
        phones = len([s for s in webui_auth.list_sessions() if s.get("remote")])
    except Exception:
        phones = 0
    checks = doc.get("checks") or {}
    return {
        "remote_access": "ENABLED" if state.get("enabled") else "DISABLED",
        "network": "Tailscale" if (doc.get("tailscale") or {}).get("ok") else "UNAVAILABLE",
        "https": "HEALTHY" if checks.get("https") else "UNHEALTHY",
        "authentication": "HEALTHY" if checks.get("authentication") else "UNHEALTHY",
        "webui": "HEALTHY" if checks.get("webui_listening") else "UNHEALTHY",
        "gateway": "PRIVATE / HEALTHY" if checks.get("gateway_private") else "EXPOSED / UNHEALTHY",
        "entity": doc.get("entity_id") or "",
        "phone_sessions": phones,
        "public_exposure": "NONE" if checks.get("funnel_off") and not (doc.get("webui") or {}).get("all_interfaces") else "LAN_OR_FUNNEL",
        "origin": doc.get("origin"),
        "doctor": doc,
    }


def ascii_qr(url: str) -> str:
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = []
        qr.print_ascii(out=type("S", (), {"write": lambda self, s: buf.append(s)})())
        return "".join(buf)
    except Exception:
        pass
    binary = shutil.which("qrencode")
    if binary:
        try:
            proc = subprocess.run(
                [binary, "-t", "UTF8", url],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ""
