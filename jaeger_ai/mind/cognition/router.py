"""
ARES SI — Router.

Selects the best worker for a task considering:
1. Policy eligibility (can this worker see this data?)
2. Capability match (can this worker do the task?)
3. Availability (is this worker reachable?)
4. Effectiveness history (how well has this worker performed?)
5. Cost and latency
6. User preference

The router is deterministic when possible, using effectiveness scores
from the worker_rankings module.
"""

from __future__ import annotations

from .types import WorkerRecord, PrivacyClass
from .worker_registry import get_registry
from .trust_engine import check_approval_required


def route_task(
    intent: str,
    data_sensitivity: str = "personal",
    require_local: bool = False,
    prefer_worker: str | None = None,
    exclude_workers: list[str] | None = None,
    profile: str | None = None,
) -> dict:
    """Select the best worker for a task.

    Returns a routing decision with:
    - selected_worker: the chosen WorkerRecord
    - alternatives: other eligible workers ranked by effectiveness
    - routing_reasons: why each worker was or wasn't selected
    - needs_approval: whether user approval is required
    """
    registry = get_registry()
    exclude = set(exclude_workers or [])

    # 1. Find eligible workers based on capability and privacy
    eligible = registry.find_eligible(
        capability=_intent_to_capability(intent),
        data_sensitivity=data_sensitivity,
        require_local=require_local,
    )

    # 2. Remove excluded workers
    eligible = [w for w in eligible if w.worker_id not in exclude]

    if not eligible:
        return {
            "selected_worker": None,
            "alternatives": [],
            "routing_reasons": {"none": "No eligible workers found for this task and sensitivity level"},
            "needs_approval": True,
            "intent": intent,
            "data_sensitivity": data_sensitivity,
        }

    # 3. If user has a preference and it's eligible, prefer it
    if prefer_worker:
        preferred = next((w for w in eligible if w.worker_id == prefer_worker), None)
        if preferred:
            return _build_routing_result(
                selected=preferred,
                alternatives=[w for w in eligible if w.worker_id != prefer_worker],
                reason=f"user_preference:{prefer_worker}",
                intent=intent,
                data_sensitivity=data_sensitivity,
                profile=profile,
            )

    # 4. Sort by effectiveness history
    effectiveness = _get_effectiveness_scores(profile)

    def sort_key(w: WorkerRecord) -> tuple:
        # Higher effectiveness → sort first (negate for ascending)
        eff = effectiveness.get(w.worker_id, 0.5)
        # Local workers get a small preference
        local_bonus = 0.05 if w.data_location == "local" else 0
        return (-(eff + local_bonus),)

    eligible.sort(key=sort_key)

    # 5. Select the best worker
    selected = eligible[0]
    alternatives = eligible[1:]

    # 6. Check if approval is needed
    needs_approval = check_approval_required(
        action=intent,
        data_sensitivity=data_sensitivity,
    )

    return _build_routing_result(
        selected=selected,
        alternatives=alternatives,
        reason=f"best_eligible:effectiveness={effectiveness.get(selected.worker_id, 'unknown')}",
        intent=intent,
        data_sensitivity=data_sensitivity,
        profile=profile,
    )


def _intent_to_capability(intent: str) -> str:
    """Map intent types to worker capabilities."""
    mapping = {
        "code_generation": "code_generation",
        "research": "research",
        "conversation": "conversation",
        "action": "terminal",
        "memory": "conversation",
    }
    return mapping.get(intent, "conversation")


def _get_effectiveness_scores(profile: str | None = None) -> dict[str, float]:
    """Load effectiveness scores from worker_rankings.

    Returns a dict of worker_id → average effectiveness (0-1 scale).
    """
    try:
        from api.worker_rankings import list_rankings
        data = list_rankings(profile)
        scores = {}
        for r in data.get("rankings", []):
            worker_id = r["worker_id"]
            avg = r.get("effectiveness_avg", 0)
            # Normalize from 0-100 scale to 0-1
            scores[worker_id] = min(avg / 100.0, 1.0) if avg > 1 else avg
        return scores
    except Exception:
        # If rankings are unavailable, return empty (all workers equal)
        return {}


def _build_routing_result(
    selected: WorkerRecord,
    alternatives: list[WorkerRecord],
    reason: str,
    intent: str,
    data_sensitivity: str,
    profile: str | None = None,
) -> dict:
    """Build the routing result dict."""
    effectiveness = _get_effectiveness_scores(profile)

    reasons = {
        selected.worker_id: reason,
    }
    for w in alternatives:
        if w.worker_id not in effectiveness:
            reasons[w.worker_id] = f"eligible_but_lower_priority:no_history"
        else:
            reasons[w.worker_id] = f"eligible_but_lower_priority:effectiveness={effectiveness[w.worker_id]:.2f}"

    return {
        "selected_worker": {
            "worker_id": selected.worker_id,
            "provider": selected.provider,
            "display_name": selected.display_name,
            "privacy_class": selected.privacy_class.value,
            "data_location": selected.data_location,
        },
        "alternatives": [
            {
                "worker_id": w.worker_id,
                "display_name": w.display_name,
                "privacy_class": w.privacy_class.value,
                "effectiveness": effectiveness.get(w.worker_id, "unknown"),
            }
            for w in alternatives
        ],
        "routing_reasons": reasons,
        "needs_approval": check_approval_required(intent, data_sensitivity),
        "intent": intent,
        "data_sensitivity": data_sensitivity,
    }