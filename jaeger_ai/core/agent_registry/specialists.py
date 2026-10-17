"""Standing Grok-shaped specialists — lead Assistant + role agents.

These are Jaeger-native agents registered through AgentRegistry (not fake
sidebar names). ``AgentRecord.role`` is lead|specialist|runtime; domain labels
(surfaces/gateway/everyday) live in ``metadata.specialty``.
"""

from __future__ import annotations

import re
from typing import Any

from jaeger_ai.core.agent_registry.types import AgentKind, AgentRecord, AgentRole

# Lead stays the primary face; specialists are callable via handoff / call_agent.
LEAD_AGENT_ID = "native:jaeger"
LEAD_NAME = "jaeger"
LEAD_DISPLAY = "Jaeger"
_OLD_LEAD_DISPLAY = "Assistant"  # pre-2026-10-09 default; migrated once
_TEST_AGENT = re.compile(r"(?i)(^|[-_])(test|probe|bench|tmp)([-_]|$)|onboarding-.*test|\.bak\.")

STANDING_SPECIALISTS: tuple[dict[str, Any], ...] = (
    {
        "name": "surfaces",
        "display_name": "Surfaces",
        "specialty": "surfaces",
        "internal": True,
        "summary": "Mac app + WebUI chrome, nav, branding, and session UX.",
        "allowed_tools": ("read_file", "search_files", "write_file", "patch", "terminal", "ide_context", "ide_diagnostics", "ide_open_file", "vision_analyze", "web_search", "web_extract", "update_plan", "get_time", "agent_notes"),
        "keywords": ("webui", "menu bar", "menubar", "sidebar", "avatar", "branding", "mac app", "swift"),
    },
    {
        "name": "gateway",
        "display_name": "Gateway",
        "specialty": "gateway",
        "internal": True,
        "summary": "Spine health, agents catalog, sessions, and approvals on :8810.",
        "allowed_tools": ("read_file", "search_files", "terminal", "exec_command", "system_status", "self_check", "list_background", "check_background", "web_search", "update_plan", "get_time", "calculate", "agent_notes"),
        "keywords": ("gateway", "8810", "sse", "approval", "approvals", "session store", "agents catalog"),
    },
    {
        "name": "everyday",
        "display_name": "Everyday",
        "specialty": "everyday",
        "summary": "Daily-driver tasks: calendar, mail, reminders, host helpers.",
        "allowed_tools": ("get_events", "create_event", "list_mailboxes", "list_mail", "read_mail", "plan_mail_triage", "move_mail", "sweep_mail", "send_email", "lookup_contact", "todo", "notify", "list_schedules", "schedule_prompt", "get_time", "calculate", "get_weather", "web_search", "web_extract", "update_plan", "agent_notes"),
        "keywords": ("calendar", "email", "mail", "inbox", "reminder", "reminders", "meeting", "schedule"),
    },
)


def _needs_seed(registry) -> bool:
    agents = registry._data.get("agents") or {}
    for spec in STANDING_SPECIALISTS:
        aid = f"native:{spec['name']}"
        entry = agents.get(aid)
        if not isinstance(entry, dict):
            return True
        if str(entry.get("role") or "") != AgentRole.SPECIALIST.value:
            return True
        specialty = (entry.get("metadata") or {}).get("specialty") or (
            entry.get("metadata") or {}
        ).get("role")
        if specialty != spec["specialty"]:
            return True
    lead = agents.get(LEAD_AGENT_ID)
    if not isinstance(lead, dict):
        return True
    if lead.get("display_name") == _OLD_LEAD_DISPLAY:  # the default, never an owner rename
        return True
    if str(lead.get("role") or "") != AgentRole.LEAD.value and (
        lead.get("metadata") or {}
    ).get("role") != "lead":
        return True
    return False


def ensure_standing_specialists(registry) -> list[AgentRecord]:
    """Idempotently register lead + standing specialists in *registry*.

    Cheap no-op when specialists already seeded with role metadata.
    Does not steal activation away from an already-active agent unless none
    is sticky yet. Returns the specialist records.
    """
    if not _needs_seed(registry):
        out = []
        for spec in STANDING_SPECIALISTS:
            # Read overlay directly — never call get_agent/list_agents (recursion).
            raw = (registry._data.get("agents") or {}).get(f"native:{spec['name']}")
            if isinstance(raw, dict):
                out.append(AgentRecord.from_dict(raw))
        return out

    lead = registry.create_agent(
        LEAD_NAME,
        kind=AgentKind.NATIVE,
        role=AgentRole.LEAD,
        display_name=LEAD_DISPLAY,
        metadata={
            "framework": "jaeger",
            "role": "lead",
            "specialty": "lead",
            "product_shape": "grok_bot",
            "summary": "Lead assistant — delegates to standing specialists.",
            "replace": True,
        },
        make_active=False,
        scaffold_instance=True,
    )
    stored = dict(lead.to_dict())
    meta = dict(stored.get("metadata") or {})
    meta.update(
        {
            "framework": "jaeger",
            "role": "lead",
            "specialty": "lead",
            "product_shape": "grok_bot",
            "summary": "Lead assistant — delegates to standing specialists.",
        }
    )
    stored["display_name"] = LEAD_DISPLAY
    stored["role"] = AgentRole.LEAD.value
    stored["metadata"] = meta
    registry._data.setdefault("agents", {})[LEAD_AGENT_ID] = stored

    out: list[AgentRecord] = []
    for spec in STANDING_SPECIALISTS:
        record = registry.create_agent(
            spec["name"],
            kind=AgentKind.NATIVE,
            role=AgentRole.SPECIALIST,
            display_name=spec["display_name"],
            metadata={
                "framework": "jaeger",
                "role": spec["specialty"],  # legacy domain label
                "specialty": spec["specialty"],
                "product_shape": "grok_bot",
                "summary": spec["summary"],
                "specialist": True,
                "replace": True,
            },
            make_active=False,
            scaffold_instance=True,
        )
        stored_s = dict(record.to_dict())
        smeta = dict(stored_s.get("metadata") or {})
        smeta.update(
            {
                "framework": "jaeger",
                "role": spec["specialty"],
                "specialty": spec["specialty"],
                "product_shape": "grok_bot",
                "summary": spec["summary"],
                "specialist": True,
            }
        )
        stored_s["display_name"] = spec["display_name"]
        stored_s["role"] = AgentRole.SPECIALIST.value
        stored_s["metadata"] = smeta
        registry._data.setdefault("agents", {})[record.id] = stored_s
        out.append(AgentRecord.from_dict(stored_s))

    if not registry._data.get("active_id"):
        registry._data["active_id"] = LEAD_AGENT_ID
        registry._write_sticky(LEAD_NAME)

    registry._save()
    return out


def specialist_ids() -> list[str]:
    return [f"native:{s['name']}" for s in STANDING_SPECIALISTS]


def is_test_agent(record) -> bool:
    """Leftover onboarding/probe instances: kept in the registry, hidden from the roster."""
    role = getattr(getattr(record, "role", None), "value", getattr(record, "role", None))
    return str(role) == "runtime" and bool(_TEST_AGENT.search(str(getattr(record, "name", "") or "")))


def specialist_tools(agent) -> list[str] | None:
    """Per-agent allowed tools (Claude Code subagent ``tools:`` list).

    ``metadata.allowed_tools`` on the registry record wins; else the standing
    definition; None when the agent has no scoped set (it stays model-only)."""
    meta = getattr(agent, "metadata", None) or {}
    own = meta.get("allowed_tools") if isinstance(meta, dict) else None
    if isinstance(own, list) and all(isinstance(x, str) for x in own):
        return list(own)
    name = str(getattr(agent, "name", "") or "")
    for spec in STANDING_SPECIALISTS:
        if spec["name"] == name:
            return list(spec.get("allowed_tools") or ())
    return None
