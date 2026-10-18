"""Standing Grok-shaped specialists — lead Assistant + role agents.

These are Jaeger-native agents registered through AgentRegistry (not fake
sidebar names). ``AgentRecord.role`` is lead|specialist|runtime; domain labels
(surfaces/gateway/everyday) live in ``metadata.specialty``.
"""

from __future__ import annotations

import re
from typing import Any

from jaeger_ai.contract.ports import GATEWAY_PORT

from jaeger_ai.core.agent_registry.types import AgentKind, AgentRecord, AgentRole

# Lead stays the primary face; specialists are callable via handoff / call_agent.
LEAD_AGENT_ID = "native:jaeger"
LEAD_NAME = "jaeger"
LEAD_DISPLAY = "Jaeger"
_OLD_LEAD_DISPLAY = "Assistant"  # pre-2026-10-09 default; migrated once
_TEST_AGENT = re.compile(r"(?i)(^|[-_])(test|probe|bench|tmp)([-_]|$)|onboarding-.*test|\.bak\.")


#: REA tools the reverse-engineer may call: static, local, read-only analysis.
#: Nothing here launches or attaches to a process, drives a device or GUI, or
#: writes an artifact (extract_artifact, export_evidence_bundle, close_binary,
#: capture_*/observe_*/frida/gdb/rizin/adb are deliberately absent). The same
#: names are the server's ``tools.read_only`` list in mcp.json, so these run
#: without a card; any other REA tool asks (plugins/mcp/client.py).
REA_READ_ONLY_TOOLS: tuple[str, ...] = (
    "open_binary", "binary_session", "binary_overview", "inspect_artifact",
    "inspect_binary_layout", "inspect_analysis_view",
    "analyze_javascript_application", "trace_application_feature",
    "trace_javascript_semantics", "compare_javascript_export_shapes", "trace_feature",
    "inspect_electron_fuses", "inspect_macho", "inspect_signature", "inspect_plist",
    "list_architectures", "demangle_swift", "decode_interface_builder",
    "inspect_keyed_archive", "inspect_asset_catalog", "trace_dylib_resolution",
    "list_strings", "search_strings", "list_procedures", "search_procedures",
    "list_segments", "list_names", "procedure_info", "procedure_assembly",
    "procedure_pseudo_code", "procedure_callers", "procedure_callees",
    "procedure_references", "xrefs", "get_call_graph", "analyze_function",
    "read_bytes", "search_bytes", "inspect_android_package", "inspect_pe_resources",
    "inspect_go_binary", "inspect_rust_binary", "inspect_sqlite_database",
    "project_apple_application_graph", "project_android_application_graph",
    "get_evidence_bundle", "list_unknowns", "evaluate_reconstruction_coverage",
    "verify_unknown_resolution", "compare_artifacts",
)

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
        "summary": f"Spine health, agents catalog, sessions, and approvals on :{GATEWAY_PORT}.",
        "allowed_tools": ("read_file", "search_files", "terminal", "exec_command", "system_status", "self_check", "list_background", "check_background", "web_search", "update_plan", "get_time", "calculate", "agent_notes"),
        "keywords": ("gateway", str(GATEWAY_PORT), "sse", "approval", "approvals", "session store", "agents catalog"),
    },
    {
        "name": "everyday",
        "display_name": "Everyday",
        "specialty": "everyday",
        "summary": "Daily-driver tasks: calendar, mail, reminders, host helpers.",
        "allowed_tools": ("get_events", "create_event", "list_mailboxes", "list_mail", "read_mail", "plan_mail_triage", "move_mail", "sweep_mail", "send_email", "lookup_contact", "todo", "notify", "list_schedules", "schedule_prompt", "get_time", "calculate", "get_weather", "web_search", "web_extract", "update_plan", "agent_notes"),
        "keywords": ("calendar", "email", "mail", "inbox", "reminder", "reminders", "meeting", "schedule"),
    },
    # Project team roles. No keywords: the lead assigns them explicitly
    # (run_team / call_agent), auto-routing never moves a chat to them.
    {
        "name": "reverse-engineer",
        "display_name": "Reverse Engineer",
        "specialty": "reverse-engineering",
        "team_role": "reverse-engineer",
        "summary": "Studies shipped apps read-only with REA and reports structure and features with evidence.",
        "allowed_tools": (*(f"mcp__rea__{n}" for n in REA_READ_ONLY_TOOLS), "read_file", "search_files", "web_search", "web_extract", "update_plan", "get_time", "agent_notes", "use_skill", "skill"),
        "skills": ("reverse-engineer-anything", "jaeger-reverse-engineer"),
        "keywords": (),
    },
    {
        "name": "builder",
        "display_name": "Builder",
        "specialty": "builder",
        "team_role": "builder",
        "summary": "Implements apps inside the project root, builds and tests them, and proves it with the checker.",
        "allowed_tools": ("read_file", "search_files", "write_file", "append_file", "patch", "move_file", "copy_file", "terminal", "exec_command", "write_stdin", "kill_command", "list_background", "check_background", "run_build_check", "update_plan", "get_time", "agent_notes", "use_skill", "skill"),
        "skills": ("jaeger-builder",),
        "keywords": (),
    },
    {
        "name": "reviewer",
        "display_name": "Reviewer",
        "specialty": "reviewer",
        "team_role": "reviewer",
        "summary": "Reviews builds against the spec and reruns the build/test checker.",
        "allowed_tools": ("read_file", "search_files", "run_build_check", "update_plan", "get_time", "agent_notes", "use_skill", "skill"),
        "skills": ("jaeger-reviewer",),
        "keywords": (),
    },
    {
        "name": "researcher",
        "display_name": "Researcher",
        "specialty": "researcher",
        "team_role": "researcher",
        "summary": "Answers outside-knowledge questions from the web and local files, with sources.",
        "allowed_tools": ("web_search", "web_extract", "read_file", "search_files", "update_plan", "get_time", "agent_notes", "use_skill", "skill"),
        "skills": ("jaeger-researcher",),
        "keywords": (),
    },
    {
        "name": "designer",
        "display_name": "Designer",
        "specialty": "designer",
        "team_role": "designer",
        "summary": "Turns findings into screen lists and UI specs a builder can implement.",
        "allowed_tools": ("read_file", "search_files", "write_file", "patch", "vision_analyze", "web_search", "update_plan", "get_time", "agent_notes", "use_skill", "skill"),
        "skills": ("jaeger-designer",),
        "keywords": (),
    },
)

#: Skills every agent loads on top of its own role skills.
SHARED_SKILLS: tuple[str, ...] = ("jaeger-team-handbook",)
#: The lead's role skills. The lead keeps the owner's full skill catalog;
#: these are surfaced first and listed on its agent record.
LEAD_SKILLS: tuple[str, ...] = ("jaeger-team-lead",)


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
                **({"team_role": spec["team_role"]} if spec.get("team_role") else {}),
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
                **({"team_role": spec["team_role"]} if spec.get("team_role") else {}),
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


def _standing(agent) -> dict[str, Any] | None:
    name = str(getattr(agent, "name", "") or "")
    return next((spec for spec in STANDING_SPECIALISTS if spec["name"] == name), None)


def _role_value(agent) -> str:
    role = getattr(agent, "role", None)
    return str(getattr(role, "value", role) or "")


def specialist_skills(agent) -> list[str] | None:
    """The agent's own role skills (by SKILL.md name).

    ``metadata.skills`` on the registry record wins; else the standing
    definition; the lead gets :data:`LEAD_SKILLS`; None for agents with no
    role skills defined."""
    meta = getattr(agent, "metadata", None) or {}
    own = meta.get("skills") if isinstance(meta, dict) else None
    if isinstance(own, list) and all(isinstance(x, str) for x in own):
        return list(own)
    spec = _standing(agent)
    if spec is not None:
        return list(spec.get("skills") or ())
    if _role_value(agent) == "lead" or getattr(agent, "id", "") == LEAD_AGENT_ID:
        return list(LEAD_SKILLS)
    return None


def scoped_skill_names(agent) -> list[str] | None:
    """Skills a specialist run may load: its own plus the shared ones.

    None means unscoped (the lead and non-specialists keep the full catalog)."""
    if _role_value(agent) != "specialist":
        return None
    own = specialist_skills(agent) or []
    return list(dict.fromkeys([*own, *SHARED_SKILLS]))


def agent_skill_names(agent) -> list[str]:
    """Every skill listed on an agent record (own + shared, lead included)."""
    own = specialist_skills(agent) or []
    if not own and _role_value(agent) not in {"specialist", "lead"}:
        return []
    return list(dict.fromkeys([*own, *SHARED_SKILLS]))


def expand_tool_patterns(names: list[str], available: set[str] | frozenset[str]) -> list[str]:
    """Expand ``mcp__rea__*``-style globs against the registered tool names.

    Exact names pass through unchanged (a missing exact tool stays listed so
    the allowlist stays honest about what was granted)."""
    import fnmatch

    out: list[str] = []
    for name in names:
        if any(ch in name for ch in "*?["):
            out.extend(sorted(n for n in available if fnmatch.fnmatchcase(n, name)))
        else:
            out.append(name)
    return list(dict.fromkeys(out))


_CARD_CACHE: dict[str, Any] = {}


def resolve_skill_cards(names: list[str], roots: list[Any]) -> list[dict[str, Any]]:
    """``[{id, name, description, source_path}]`` for skill names, first root wins.

    Roots are skills directories (instance first, then bundled). A name with no
    SKILL.md on disk is still listed, with ``source_path: None`` and
    ``missing: True``, so the UI shows an uninstalled skill instead of hiding it."""
    from pathlib import Path

    from jaeger_agent.skill_registry.playbook_skills import _parse_frontmatter

    index: dict[str, tuple[str, str]] = {}
    for root in reversed([Path(r) for r in roots if r]):
        if not root.is_dir():
            continue
        try:
            sig = (str(root), root.stat().st_mtime_ns)
        except OSError:
            continue
        cached = _CARD_CACHE.get(str(root))
        if cached is None or cached[0] != sig:
            found: dict[str, tuple[str, str]] = {}
            for md in root.rglob("SKILL.md"):
                try:
                    fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
                except OSError:
                    continue
                name = str(fm.get("name") or md.parent.name)
                found[name] = (str(md.parent), " ".join(str(fm.get("description") or "").split()))
            cached = (sig, found)
            _CARD_CACHE[str(root)] = cached
        index.update(cached[1])
    cards = []
    for name in names:
        hit = index.get(name)
        card = {"id": name, "name": name,
                "description": hit[1] if hit else "",
                "source_path": hit[0] if hit else None}
        if hit is None:
            card["missing"] = True
        cards.append(card)
    return cards
