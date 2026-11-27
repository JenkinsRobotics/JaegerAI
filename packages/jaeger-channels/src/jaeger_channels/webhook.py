"""Outbound webhook transport slice for jaeger-channels.

One concrete, standard-library-only outbound channel: a single JSON POST to an
owner/admin-configured endpoint that is fixed at construction time.

Safety properties:
- The endpoint URL is validated at construction: HTTPS, or plain HTTP only for
  an explicit numeric loopback address (local installs). URL userinfo,
  fragments, control characters, and invalid ports are rejected.
- The recipient is JSON payload data only — it is never interpolated into the
  URL. The POST always goes to exactly the configured endpoint.
- No redirects are followed and no ambient proxy (env vars) is used: a
  dedicated opener with an empty ProxyHandler and a redirect handler that
  refuses every redirect.
- Optional Bearer token is sent as an Authorization header (validated to be
  printable ASCII so it cannot inject header bytes).
- The persisted receipt never contains the raw response body or exception
  text (either may embed the endpoint or token). Only a confirmed 2xx yields
  ``delivered: true`` plus ``http_status``.
- Delivery itself is still gated by ``ChannelHub``: the adapter is only invoked
  for messages explicitly approved by the owner (``approve_delivery`` or
  ``enqueue(..., approved=True)``); everything else stays queued.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

__all__ = ["WEBHOOK_TIMEOUT_S", "WebhookConfigError", "build_webhook_adapter"]

#: Short bounded timeout (seconds) for the single POST.
WEBHOOK_TIMEOUT_S = 5.0

#: Upper bound for any caller-supplied timeout, keeping sends short.
_MAX_TIMEOUT_S = 30.0


class WebhookConfigError(ValueError):
    """The owner-configured webhook URL/token is not acceptable (fail closed)."""


def _is_numeric_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_webhook_url(url: str) -> str:
    """Return ``url`` unchanged if acceptable, else raise ``WebhookConfigError``."""
    if not isinstance(url, str) or not url:
        raise WebhookConfigError("webhook URL must be a non-empty string")
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        # Rejects control characters (and raw spaces) before any parsing.
        raise WebhookConfigError("webhook URL contains control characters")
    if "#" in url:
        raise WebhookConfigError("webhook URL must not contain a fragment")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise WebhookConfigError("webhook URL is malformed") from exc
    if parts.scheme not in ("https", "http"):
        raise WebhookConfigError("webhook URL must use https (or numeric loopback http)")
    if parts.username is not None or parts.password is not None:
        raise WebhookConfigError("webhook URL must not embed userinfo credentials")
    host = parts.hostname
    if not host:
        raise WebhookConfigError("webhook URL must have a host")
    if parts.scheme == "http" and not _is_numeric_loopback(host):
        raise WebhookConfigError(
            "plain http is only allowed for an explicit numeric loopback address"
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise WebhookConfigError("webhook URL has an invalid port") from exc
    if port is not None and port < 1:
        raise WebhookConfigError("webhook URL has an invalid port")
    return url


def _validate_token(token: str) -> str:
    if not token:
        raise WebhookConfigError("webhook token must be non-empty when provided")
    if any(not (0x21 <= ord(ch) <= 0x7E) for ch in token):
        # Printable ASCII only: no control bytes, spaces, or non-ASCII that
        # could break/inject into the Authorization header.
        raise WebhookConfigError("webhook token contains invalid characters")
    return token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: returning None makes urllib raise HTTPError."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def build_webhook_adapter(
    url: str,
    token: str | None = None,
    *,
    timeout_s: float = WEBHOOK_TIMEOUT_S,
) -> Callable[[str, str], dict[str, Any]]:
    """Build a ``webhook`` channel adapter POSTing JSON to a fixed endpoint.

    The returned callable matches the ChannelHub adapter contract
    ``(recipient, body) -> receipt``. ``recipient`` is embedded as JSON data in
    the request body, never in the URL. Construction performs no network I/O.

    Raises ``WebhookConfigError`` for an unacceptable URL or token, so callers
    can fail closed at wiring time.
    """
    endpoint = _validate_webhook_url(url)
    auth_value = f"Bearer {_validate_token(token)}" if token is not None else None
    if not (isinstance(timeout_s, (int, float)) and 0 < float(timeout_s) <= _MAX_TIMEOUT_S):
        raise WebhookConfigError("webhook timeout must be a positive, bounded number of seconds")
    timeout = float(timeout_s)

    # Dedicated opener: empty ProxyHandler disables ambient proxy env vars;
    # _NoRedirect makes any 3xx surface as HTTPError instead of being followed.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def adapter(recipient: str, body: str) -> dict[str, Any]:
        payload = json.dumps(
            {"recipient": recipient, "body": body}, ensure_ascii=False
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "jaeger-channels-webhook/0.1",
        }
        if auth_value is not None:
            headers["Authorization"] = auth_value
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=timeout) as resp:
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            # Non-2xx (including refused redirects). Never persist the response
            # body or the exception text — both may embed endpoint secrets.
            return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
        except (urllib.error.URLError, OSError):
            # URLError/OSError text can embed the URL and reason: not persisted.
            return {"delivered": False, "error": "request_failed"}
        except Exception:  # noqa: BLE001 - fail closed with a generic receipt
            return {"delivered": False, "error": "adapter_error"}
        if 200 <= status < 300:
            return {"delivered": True, "http_status": status}
        return {"delivered": False, "http_status": status, "error": "unexpected_status"}

    return adapter
