"""Standard Web Push (RFC 8030 / 8291 aes128gcm / 8292 VAPID) with ``cryptography`` only.

pywebpush is not installed in the Jaeger venv; this module implements the two
pieces it would provide (payload encryption and the VAPID JWT) on top of
``cryptography`` (already a dependency), so no new package is needed.

Secrets live in ``<state>/secrets`` (``JAEGER_SECRETS_DIR`` overrides; default
``~/.jaeger/secrets``), directory 0700, files 0600:
  vapid.json               {"private_key_pem", "created_at"} — never logged, printed or returned
  push_subscriptions.json  [{id, endpoint, keys{p256dh,auth}, device_label, platform, standalone, ...}]
Nothing is created until a push route is first used, or the owner runs once:
  python -m jaeger_ai.core.gateway.webpush init-vapid      (prints the PUBLIC key only)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")
MAX_PAYLOAD = 4000
_lock = threading.RLock()


class PushError(ValueError):
    pass


def secrets_dir(create: bool = True) -> Path:
    raw = os.environ.get("JAEGER_SECRETS_DIR", "").strip()
    if raw:
        d = Path(raw).expanduser()
    else:
        from jaeger_ai.core.instance.instance import StatePaths
        d = StatePaths.resolve().state_root / "secrets"  # pure: no mkdir/migration on reads
    if create:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def _write_private(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_pub(pub) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_private_key():
    """Load the instance VAPID key, generating it once (0600) if absent."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = secrets_dir() / "vapid.json"
    with _lock:
        if not path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            _write_private(path, {"private_key_pem": pem, "created_at": time.time()})
        os.chmod(path, 0o600)
        pem = json.loads(path.read_text("utf-8"))["private_key_pem"]
    return serialization.load_pem_private_key(pem.encode(), password=None)


def vapid_public_key() -> str:
    return b64u(_raw_pub(vapid_private_key().public_key()))


def vapid_authorization(endpoint: str, subject: str, *, now: float | None = None, ttl_s: int = 12 * 3600) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urlparse(endpoint)
    key = vapid_private_key()
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(now or time.time()) + ttl_s,
                              "sub": subject}, separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={b64u(_raw_pub(key.public_key()))}"


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """RFC 8291 aes128gcm body (single record)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ua_raw, secret = unb64u(p256dh), unb64u(auth)
    ua = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_raw)
    eph = ec.generate_private_key(ec.SECP256R1())
    as_raw = _raw_pub(eph.public_key())
    ikm = HKDF(hashes.SHA256(), 32, secret, b"WebPush: info\x00" + ua_raw + as_raw).derive(eph.exchange(ec.ECDH(), ua))
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    return salt + struct.pack("!IB", 4096, len(as_raw)) + as_raw + AESGCM(cek).encrypt(nonce, payload + b"\x02", None)


def allowed_endpoint(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))


def http_post(url: str, data: bytes, headers: dict[str, str]) -> int:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


# ── subscriptions ─────────────────────────────────────────────────────
def _subs_path() -> Path:
    return secrets_dir() / "push_subscriptions.json"


def list_subscriptions() -> list[dict]:
    path = secrets_dir(create=False) / "push_subscriptions.json"
    try:
        subs = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return subs if isinstance(subs, list) else []


def public_view(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "device_label", "platform", "standalone", "created_at", "last_sent_at",
                                  "last_status")} | {"push_service": urlparse(s.get("endpoint", "")).hostname}


def add_subscription(body: dict) -> tuple[dict, bool]:
    endpoint = str(body.get("endpoint") or "")
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    if not allowed_endpoint(endpoint):
        raise PushError("endpoint must be an https URL on a known push service")
    try:
        if len(unb64u(str(keys.get("p256dh") or ""))) != 65 or len(unb64u(str(keys.get("auth") or ""))) != 16:
            raise ValueError
    except Exception as exc:  # noqa: BLE001
        raise PushError("keys.p256dh (65 bytes) and keys.auth (16 bytes) are required, base64url") from exc
    sid = "psub_" + hashlib.sha256(endpoint.encode()).hexdigest()[:16]
    rec = {"id": sid, "endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
           "device_label": str(body.get("device_label") or "")[:80], "platform": str(body.get("platform") or "")[:40],
           "standalone": bool(body.get("standalone")), "created_at": time.time()}
    with _lock:
        subs = list_subscriptions()
        existing = next((s for s in subs if s.get("id") == sid), None)
        subs = [s for s in subs if s.get("id") != sid] + [{**(existing or {}), **rec,
                                                            "created_at": (existing or rec)["created_at"]}]
        _write_private(_subs_path(), subs)
    return public_view(rec), existing is None


def remove_subscription(sid: str) -> bool:
    with _lock:
        subs = list_subscriptions()
        keep = [s for s in subs if s.get("id") != sid]
        if len(keep) != len(subs):
            _write_private(_subs_path(), keep)
        return len(keep) != len(subs)


def send(payload: dict, *, subject: str, urgency: str = "normal", ttl: int = 86400,
         only: str | None = None, poster=None) -> dict:
    """Encrypt and POST one payload to every (or one) subscription; drop 404/410 endpoints."""
    data = json.dumps(payload, separators=(",", ":")).encode()
    if len(data) > MAX_PAYLOAD:
        raise PushError("push payload exceeds 4 KB")
    post = poster or http_post
    results, delivered, dropped = [], 0, 0
    with _lock:
        subs = list_subscriptions()
        keep = []
        for s in subs:
            if only and s.get("id") != only:
                keep.append(s); continue
            try:
                status: Any = post(s["endpoint"], encrypt(data, s["keys"]["p256dh"], s["keys"]["auth"]), {
                    "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl),
                    "Urgency": urgency, "Topic": str(payload.get("tag") or "")[:32].replace(":", "-") or "jaeger",
                    "Authorization": vapid_authorization(s["endpoint"], subject)})
            except Exception as exc:  # noqa: BLE001
                status = f"error:{type(exc).__name__}"
            results.append({"id": s.get("id"), "status": status})
            if status in (404, 410):
                dropped += 1; continue
            if isinstance(status, int) and 200 <= status < 300:
                delivered += 1; s["last_sent_at"] = time.time()
            s["last_status"] = status
            keep.append(s)
        if subs:
            _write_private(_subs_path(), keep)
    return {"delivered": delivered, "dropped": dropped, "results": results}


def main(argv: list[str] | None = None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["init-vapid"]:
        print("usage: python -m jaeger_ai.core.gateway.webpush init-vapid")
        return 2
    print(json.dumps({"public_key": vapid_public_key(), "stored_in": str(secrets_dir() / "vapid.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
