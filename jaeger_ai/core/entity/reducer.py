"""Deterministic State Reducers for Jaeger Entity (Pinocchio Architecture).

Pure functions mapping (SelfState, JaegerEvent) -> SelfState.
Enables exact, reproducible state reconstruction from the persistent event log.
"""

from __future__ import annotations

from typing import Iterable

from .events import EventType, JaegerEvent
from .self_state import SelfState


def reduce_event(state: SelfState, event: JaegerEvent) -> SelfState:
    """Apply a single JaegerEvent to SelfState, returning the new immutable state."""
    etype = event.event_type
    payload = event.payload or {}
    ts = event.timestamp

    # Base updates common to all events
    last_event_ts = max(state.last_event_timestamp, ts)
    total_processed = state.total_events_processed + 1

    last_user_ts = state.last_user_interaction_ts
    current_activity = state.current_activity
    current_focus = state.current_focus
    active_interfaces = set(state.active_interfaces)
    active_sensors = set(state.active_sensors)
    active_goals = list(state.active_goals)
    commitments = list(state.commitments)
    resource_telemetry = dict(state.resource_telemetry)
    recent_insights = list(state.recent_insights)
    uncertainty_areas = list(state.uncertainty_areas)

    if event.source and event.source.startswith("sensor."):
        active_sensors.add(event.source.split(".", 1)[1])
    elif event.source and event.source in {"gateway", "bridge", "tui", "cli", "swift"}:
        active_interfaces.add(event.source)

    if etype == EventType.HUMAN_MESSAGE.value:
        last_user_ts = max(last_user_ts, ts)
        current_activity = "processing_turn"
        focus_candidate = payload.get("focus") or payload.get("workspace")
        if focus_candidate:
            current_focus = str(focus_candidate)

    elif etype == EventType.TOOL_STARTED.value:
        tool_name = str(payload.get("tool") or "")
        current_activity = f"tool_executing:{tool_name}" if tool_name else "tool_executing"

    elif etype in (EventType.TOOL_COMPLETED.value, EventType.TOOL_FAILED.value):
        current_activity = "idle"
        if etype == EventType.TOOL_FAILED.value:
            err_msg = str(payload.get("error") or "Unknown tool failure")
            tool_name = str(payload.get("tool") or "tool")
            uncertainty_areas.append(f"{tool_name}: {err_msg}")
            uncertainty_areas = uncertainty_areas[-10:]

    elif etype == EventType.AGENT_RESPONSE.value:
        current_activity = "idle"

    elif etype == EventType.GOAL_CREATED.value:
        gid = payload.get("id") or f"goal-{total_processed}"
        desc = payload.get("description") or payload.get("desc") or ""
        active_goals.append({"id": str(gid), "description": str(desc), "created_at": ts})

    elif etype == EventType.GOAL_COMPLETED.value:
        gid = str(payload.get("id") or "")
        active_goals = [g for g in active_goals if g.get("id") != gid]

    elif etype == EventType.COMMITMENT_CREATED.value:
        cid = payload.get("id") or f"cmt-{total_processed}"
        commitments.append({
            "id": str(cid),
            "description": str(payload.get("description") or ""),
            "target": str(payload.get("target") or ""),
            "created_at": ts,
        })

    elif etype == EventType.COMMITMENT_UPDATED.value:
        cid = str(payload.get("id") or "")
        status = str(payload.get("status") or "")
        if status in {"completed", "abandoned", "resolved"}:
            commitments = [c for c in commitments if c.get("id") != cid]
        else:
            for c in commitments:
                if c.get("id") == cid:
                    c.update(payload)

    elif etype == EventType.PERCEPTION_SENSED.value:
        for k, v in payload.items():
            if k in ("disk_free_gb", "load_avg", "dirty_files", "idle_seconds", "active_app"):
                resource_telemetry[k] = v
        if "focus" in payload:
            current_focus = str(payload["focus"])

    elif etype == EventType.MEMORY_CONSOLIDATED.value:
        new_insights = payload.get("insights") or []
        if isinstance(new_insights, list):
            recent_insights.extend(str(x) for x in new_insights)
            recent_insights = recent_insights[-20:]

    return SelfState(
        identity=state.identity,
        boot_timestamp=state.boot_timestamp,
        last_event_timestamp=last_event_ts,
        last_user_interaction_ts=last_user_ts,
        current_activity=current_activity,
        current_focus=current_focus,
        active_interfaces=tuple(sorted(active_interfaces)),
        active_sensors=tuple(sorted(active_sensors)),
        active_goals=tuple(active_goals),
        commitments=tuple(commitments),
        important_people=state.important_people,
        uncertainty_areas=tuple(uncertainty_areas),
        resource_telemetry=resource_telemetry,
        recent_insights=tuple(recent_insights),
        total_events_processed=total_processed,
    )


def replay_events(initial_state: SelfState, events: Iterable[JaegerEvent]) -> SelfState:
    """Rebuild current SelfState by playing all events sequentially through reduce_event."""
    state = initial_state
    for evt in events:
        state = reduce_event(state, evt)
    return state
