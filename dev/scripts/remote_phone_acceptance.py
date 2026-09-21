#!/usr/bin/env python3
"""Isolated + operator remote-access checks. Does not wipe the operator fabric."""
from __future__ import annotations

import json
import os
import ssl
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ORIGIN = "https://matthews-mac-studio.tail80f206.ts.net:8443"
GATEWAY = "http://127.0.0.1:8810"


def _json(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 8.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            parsed = json.loads(raw.decode() or "null") if raw else None
            return {"status": resp.status, "body": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode() or "null")
        except Exception:
            parsed = raw[:200].decode("utf-8", "replace")
        return {"status": exc.code, "body": parsed}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


def isolated(tmp: Path) -> dict:
    os.environ["JAEGER_STATE_DIR"] = str(tmp)
    os.environ["JAEGER_INSTANCE_DIR"] = str(tmp / "inst")
    (tmp / "inst" / "run").mkdir(parents=True)
    from jaeger_ai.features.remote_access.service import consume_pairing_token, enable, issue_pairing_token
    from jaeger_ai.features.remote_access.service import disable as remote_disable
    from jaeger_ai.features.remote_access.service import tailscale_status as real_ts
    import jaeger_ai.features.remote_access.service as svc
    svc.tailscale_status = lambda: {
        "ok": True, "installed": True, "logged_in": True,
        "dns_name": "isolated.tailnet.ts.net", "ipv4": "100.64.9.9",
    }
    res = enable(start_webui=False, serve=False)
    pair = issue_pairing_token()
    ok = bool(res.get("ok")) and consume_pairing_token(pair["token"]) and not consume_pairing_token(pair["token"])
    remote_disable(stop_serve=False)
    svc.tailscale_status = real_ts
    return {"ok": ok, "origin": res.get("origin"), "pair": pair["url"]}


def operator_snapshot() -> dict:
    import urllib.error
    gw = _json("GET", GATEWAY + "/v1/runtime/status")
    entity = ""
    if isinstance(gw.get("body"), dict):
        entity = str(((gw["body"].get("Agent") or {}).get("entity_id")) or "")
    sessions_https = _json("GET", ORIGIN + "/api/jaeger/sessions")
    auth = _json("GET", ORIGIN + "/api/auth/status")
    gw_tailnet = _json("GET", "http://100.74.2.15:8810/health")
    return {
        "entity_id": entity,
        "gateway_loopback": gw.get("status") == 200,
        "gateway_tailnet_closed": gw_tailnet.get("status") in {0, None} or "error" in gw_tailnet,
        "https_webui": sessions_https.get("status") in {200, 401, 403},
        "unauth_sessions_status": sessions_https.get("status"),
        "auth_enabled": bool((auth.get("body") or {}).get("auth_enabled")) if isinstance(auth.get("body"), dict) else False,
        "auth_status": auth.get("body"),
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jaeger-remote-"))
    iso = isolated(tmp)
    snap = operator_snapshot()
    from jaeger_ai.features.remote_access.service import doctor, status_report
    doc = doctor()
    status = status_report()
    out = {"isolated": iso, "operator": snap, "doctor": doc, "status": status}
    print(json.dumps(out, indent=2, default=str)[:12000])
    iso_ok = bool(iso.get("ok"))
    gw_ok = bool(snap.get("gateway_loopback") and snap.get("gateway_tailnet_closed"))
    https_ok = bool(snap.get("https_webui"))
    auth_ok = bool(snap.get("auth_enabled")) and int(snap.get("unauth_sessions_status") or 0) in {401, 403}
    return 0 if iso_ok and gw_ok and https_ok and auth_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
