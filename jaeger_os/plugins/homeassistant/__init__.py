"""Home Assistant plugin — read + control smart-home devices via the HA REST API.

Registers four INDIVIDUAL agent tools (measured: individual named tools
beat an ``action=`` umbrella for the 4B — dev/docs/reality/agentic_runners.md):

  • ha_list_entities(domain, area)  — enumerate devices, compact summary
  • ha_get_state(entity_id)         — one entity, full attributes
  • ha_list_services(domain)        — what actions each domain supports
  • ha_call_service(domain, service, entity_id, data_json) — do the thing

Ported from Hermes (tools/homeassistant_tool.py) with the JROS contract:
tools return dicts (never raise), credentials resolve instance-store first
(``HASS_URL`` / ``HASS_TOKEN`` via set_credential) with env-var fallback,
and every tool returns a friendly ``{ok: False, error: …}`` setup guide
when unconfigured. ``ha_call_service`` is tier-gated (EXTERNAL_EFFECT),
matching ``send_message``.

Registration follows the send_message pattern: importing this module
registers the tools (``main._register_builtins`` imports it); the
``register(ctx)`` entry point exists for the plugin-extension surface
(``jaeger_os.plugins.registry.discover_plugins``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from jaeger_os.agent.schemas.tool_registry import (
    get_tool,
    register_tool_from_function,
)
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

# ---------------------------------------------------------------------------
# Configuration — instance credential store first, env fallback
# ---------------------------------------------------------------------------

_DEFAULT_URL = "http://homeassistant.local:8123"
_TIMEOUT = 5.0  # seconds — short; HA lives on the LAN

_SETUP_HELP = (
    "Home Assistant is not configured: no HASS_TOKEN found. "
    "Create a long-lived access token in Home Assistant (Profile → Security → "
    "Long-lived access tokens), then save it with "
    "set_credential('HASS_TOKEN', <token>) and your instance URL with "
    "set_credential('HASS_URL', 'http://homeassistant.local:8123') "
    "(or export HASS_TOKEN / HASS_URL in the environment)."
)


def _layout_or_none() -> Any:
    """The bound instance layout, or None when tools aren't bound yet
    (bare imports, unit tests). Seam for tests."""
    try:
        from jaeger_os.core.context import get_layout
        return get_layout()
    except Exception:  # noqa: BLE001 — unbound → env fallback only
        return None


def _credential(*names: str) -> str:
    """Resolve a secret: instance credential store first (each candidate
    name), then the FIRST name as an env var. Mirrors
    ``jaeger_os.plugins.plugin_credential`` with alias support."""
    layout = _layout_or_none()
    if layout is not None:
        from jaeger_os.core import credentials as creds
        for name in names:
            try:
                value = creds.get_credential(layout, name)
                if value:
                    return value
            except Exception:  # noqa: BLE001 — absent/garbled → next candidate
                continue
    return (os.environ.get(names[0]) or "").strip()


def _get_config() -> tuple[str, str]:
    """Return ``(base_url, token)``. URL defaults to the standard
    homeassistant.local address; token empty means unconfigured."""
    url = _credential("HASS_URL", "homeassistant_url") or _DEFAULT_URL
    token = _credential("HASS_TOKEN", "homeassistant_token")
    return url.rstrip("/"), token


# ---------------------------------------------------------------------------
# Validation (ported from Hermes — the security layer, HA has none)
# ---------------------------------------------------------------------------

# Valid HA entity_id format (e.g. "light.living_room", "sensor.temp_1").
_ENTITY_ID_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")

# Valid HA domain/service names. Only lowercase letters, digits, and
# underscores — no slashes/dots that could path-traverse the
# /api/services/{domain}/{service} URL (SSRF / blocklist bypass like
# domain="shell_command/../light").
_SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Service domains blocked for security — these allow arbitrary code /
# command execution on the HA host or SSRF against the local network.
_BLOCKED_DOMAINS = frozenset({
    "shell_command",    # arbitrary shell commands in the HA container
    "command_line",     # sensors/switches that execute shell commands
    "python_script",    # sandboxed but can escalate via hass.services.call()
    "pyscript",         # scripting integration with broader access
    "hassio",           # addon control, host shutdown/reboot
    "rest_command",     # HTTP requests from the HA server (SSRF vector)
})

# Soft cap so an unfiltered entity dump never floods a 4B's context.
_MAX_ENTITIES = 300


# ---------------------------------------------------------------------------
# HTTP layer (requests — already a hard dep; mocked in unit tests)
# ---------------------------------------------------------------------------

def _api_get(path: str, base_url: str, token: str) -> Any:
    import requests
    resp = requests.get(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, payload: dict, base_url: str, token: str) -> Any:
    import requests
    resp = requests.post(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _unreachable(base_url: str, exc: Exception) -> dict:
    return {"ok": False, "error": (
        f"Home Assistant at {base_url} did not answer: "
        f"{type(exc).__name__}: {exc}. Check the URL (HASS_URL), that the "
        f"instance is up, and that the token is valid."
    )}


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without HTTP)
# ---------------------------------------------------------------------------

def _filter_and_summarize(states: list, domain: str = "",
                          area: str = "") -> dict[str, Any]:
    """Filter raw HA states by domain/area, return a compact summary."""
    if domain:
        states = [s for s in states
                  if s.get("entity_id", "").startswith(f"{domain}.")]
    if area:
        area_lower = area.lower()
        states = [
            s for s in states
            if area_lower in (s.get("attributes", {}).get("friendly_name", "") or "").lower()
            or area_lower in (s.get("attributes", {}).get("area", "") or "").lower()
        ]
    entities = [{
        "entity_id": s["entity_id"],
        "state": s["state"],
        "friendly_name": s.get("attributes", {}).get("friendly_name", ""),
    } for s in states]
    out: dict[str, Any] = {"ok": True, "count": len(entities),
                           "entities": entities[:_MAX_ENTITIES]}
    if len(entities) > _MAX_ENTITIES:
        out["truncated"] = True
        out["hint"] = "narrow with domain= or area= to see the rest"
    return out


def _build_service_payload(entity_id: str = "",
                           data: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON payload for a HA service call. ``entity_id`` argument wins
    over any entity_id inside ``data`` (Hermes parity)."""
    payload: dict[str, Any] = {}
    if data:
        payload.update(data)
    if entity_id:
        payload["entity_id"] = entity_id
    return payload


# ---------------------------------------------------------------------------
# Agent-facing tools
# ---------------------------------------------------------------------------

@register_tool_from_function(name="ha_list_entities", side_effect="read")
def ha_list_entities(domain: str = "", area: str = "") -> dict:
    """List Home Assistant smart-home entities (devices) with their
    current state. Filter by domain ('light', 'switch', 'climate',
    'sensor', 'binary_sensor', 'cover', 'lock', 'fan', 'media_player')
    and/or by area/room name ('living room', 'kitchen' — matched
    against friendly names). Call with no arguments to list everything.
    Use this FIRST to find the exact entity_id before ha_get_state or
    ha_call_service."""
    base_url, token = _get_config()
    if not token:
        return {"ok": False, "error": _SETUP_HELP}
    try:
        states = _api_get("/api/states", base_url, token)
    except Exception as exc:  # noqa: BLE001 — network errors → tool result
        return _unreachable(base_url, exc)
    return _filter_and_summarize(states, domain=(domain or "").strip(),
                                 area=(area or "").strip())


@register_tool_from_function(name="ha_get_state", side_effect="read")
def ha_get_state(entity_id: str) -> dict:
    """Get the detailed state of ONE Home Assistant entity, including
    all attributes (brightness, color, temperature setpoint, sensor
    reading, lock state, battery). entity_id is the full id from
    ha_list_entities, e.g. 'light.living_room' or 'lock.front_door'."""
    eid = (entity_id or "").strip()
    if not eid:
        return {"ok": False, "error": "entity_id is required (e.g. 'light.living_room')"}
    if not _ENTITY_ID_RE.match(eid):
        return {"ok": False, "error": f"invalid entity_id format: {eid!r} "
                                      f"(expected 'domain.object_id')"}
    base_url, token = _get_config()
    if not token:
        return {"ok": False, "error": _SETUP_HELP}
    try:
        data = _api_get(f"/api/states/{eid}", base_url, token)
    except Exception as exc:  # noqa: BLE001
        return _unreachable(base_url, exc)
    return {
        "ok": True,
        "entity_id": data.get("entity_id", eid),
        "state": data.get("state", ""),
        "attributes": data.get("attributes", {}),
        "last_changed": data.get("last_changed"),
        "last_updated": data.get("last_updated"),
    }


@register_tool_from_function(name="ha_list_services", side_effect="read")
def ha_list_services(domain: str = "") -> dict:
    """List the Home Assistant services (actions) available per domain —
    what you can DO to devices and which fields each action accepts.
    Filter by domain ('light', 'climate', 'cover'…) or omit for all.
    Use this to discover the right service + data fields before
    ha_call_service."""
    base_url, token = _get_config()
    if not token:
        return {"ok": False, "error": _SETUP_HELP}
    try:
        services = _api_get("/api/services", base_url, token)
    except Exception as exc:  # noqa: BLE001
        return _unreachable(base_url, exc)
    dom = (domain or "").strip()
    if dom:
        services = [s for s in services if s.get("domain") == dom]
    result = []
    for svc_domain in services:
        domain_services: dict[str, Any] = {}
        for svc_name, svc_info in (svc_domain.get("services") or {}).items():
            entry: dict[str, Any] = {"description": svc_info.get("description", "")}
            fields = svc_info.get("fields") or {}
            if fields:
                entry["fields"] = {k: v.get("description", "")
                                   for k, v in fields.items()
                                   if isinstance(v, dict)}
            domain_services[svc_name] = entry
        result.append({"domain": svc_domain.get("domain", ""),
                       "services": domain_services})
    return {"ok": True, "count": len(result), "domains": result}


@register_tool_from_function(name="ha_call_service")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="homeassistant",
               operation="call_service",
               summary="control a smart-home device via Home Assistant")
def ha_call_service(domain: str, service: str, entity_id: str = "",
                    data_json: str = "") -> dict:
    """Call a Home Assistant service to CONTROL a device — turn things
    on/off, set temperature, lock doors, run scenes. Examples:
    ha_call_service(domain='light', service='turn_on',
    entity_id='light.living_room', data_json='{"brightness": 128}');
    ha_call_service(domain='climate', service='set_temperature',
    entity_id='climate.thermostat', data_json='{"temperature": 21}').
    data_json is optional extra fields as a JSON object string. Use
    ha_list_services to discover services and their fields."""
    dom = (domain or "").strip()
    svc = (service or "").strip()
    if not dom or not svc:
        return {"ok": False, "error": "domain and service are both required "
                                      "(e.g. domain='light', service='turn_on')"}
    # Format validation BEFORE the blocklist check — prevents path
    # traversal in /api/services/{domain}/{service} and blocklist bypass.
    if not _SERVICE_NAME_RE.match(dom):
        return {"ok": False, "error": f"invalid domain format: {dom!r}"}
    if not _SERVICE_NAME_RE.match(svc):
        return {"ok": False, "error": f"invalid service format: {svc!r}"}
    if dom in _BLOCKED_DOMAINS:
        return {"ok": False, "error": (
            f"service domain {dom!r} is blocked for security (it can run "
            f"arbitrary code on the HA host). Blocked domains: "
            f"{', '.join(sorted(_BLOCKED_DOMAINS))}")}
    eid = (entity_id or "").strip()
    if eid and not _ENTITY_ID_RE.match(eid):
        return {"ok": False, "error": f"invalid entity_id format: {eid!r}"}
    data: dict[str, Any] | None = None
    if (data_json or "").strip():
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"data_json is not valid JSON: {exc}"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "data_json must be a JSON object, "
                                          "e.g. '{\"brightness\": 128}'"}
    base_url, token = _get_config()
    if not token:
        return {"ok": False, "error": _SETUP_HELP}
    payload = _build_service_payload(eid, data)
    try:
        result = _api_post(f"/api/services/{dom}/{svc}", payload,
                           base_url, token)
    except Exception as exc:  # noqa: BLE001
        return _unreachable(base_url, exc)
    affected = []
    if isinstance(result, list):
        affected = [{"entity_id": s.get("entity_id", ""),
                     "state": s.get("state", "")} for s in result]
    return {"ok": True, "service": f"{dom}.{svc}",
            "affected_entities": affected}


TOOL_NAMES = ("ha_list_entities", "ha_get_state",
              "ha_list_services", "ha_call_service")


def register(ctx: Any) -> None:
    """Plugin entry point (``jaeger_os.plugins`` group). The tools are
    already in the process-wide registry (module import registered
    them); this hands their ToolDefs to the PluginContext so the
    extension surface sees them too."""
    for name in TOOL_NAMES:
        ctx.register_tool(get_tool(name))


__all__ = ["ha_list_entities", "ha_get_state", "ha_list_services",
           "ha_call_service", "register", "TOOL_NAMES"]
