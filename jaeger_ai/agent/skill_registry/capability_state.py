"""Per-capability state + history for v3 skills.

Layout (per the spec, ``dev/docs/history/skill_schema_v3-v1.md``)::

    <instance>/skills/<id>/
      manifest.yaml      # full v3 manifest
      state.yaml         # current_level + counters PER CAPABILITY
      history.jsonl      # one line per execution, scored

This module owns the read/write of ``state.yaml`` + ``history.jsonl``,
plus the **level promotion / demotion logic** spelled out in the spec
(3 consecutive runs above the next band → promote; 3 below the
current floor → demote).  It does NOT decide *when* to run a scorer;
``skill_benchmark.py`` is the existing entry point for that and gets
wired into this module via :func:`record_capability_run`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from jaeger_ai.agent.skill_registry.manifest_v3 import Capability, Manifest


STATE_SCHEMA = "jros.skill_state/v1"

# Number of consecutive runs required to move a capability level one
# step up or down.  Conservative — sustained signal, not single runs.
PROMOTION_WINDOW = 3
DEMOTION_WINDOW = 3


# ─── data types ──────────────────────────────────────────────────────


@dataclass
class CapabilityState:
    """Mutable per-capability state — written back to ``state.yaml``."""

    current_level: int = 1
    runs_total: int = 0
    runs_at_current_level: int = 0
    last_score: float | None = None
    last_run_at: str | None = None        # ISO 8601 UTC


@dataclass
class SkillState:
    schema: str = STATE_SCHEMA
    skill_id: str = ""
    skill_version: str = ""
    capabilities: dict[str, CapabilityState] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRecord:
    """One ``history.jsonl`` line.  Same shape produced by
    ``skill_benchmark.py``'s scorer contract; this just adds the
    capability id + ISO timestamp."""

    ts: str
    cap: str
    score: float
    passed: int
    total: int
    artifact: str | None = None


# ─── disk I/O ────────────────────────────────────────────────────────


def state_path(skill_folder: Path) -> Path:
    return skill_folder / "state.yaml"


def history_path(skill_folder: Path) -> Path:
    return skill_folder / "history.jsonl"


def load_state(skill_folder: Path) -> SkillState | None:
    """Read ``state.yaml`` if it exists; ``None`` if absent or
    malformed (callers treat None as "fresh, no runs yet").

    Individual capability rows with bad numeric fields are dropped
    silently rather than nuking the whole file — a single corrupt
    capability shouldn't reset the whole skill's level history.
    """
    path = state_path(skill_folder)
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != STATE_SCHEMA:
        return None
    caps_raw = raw.get("capabilities") or {}
    caps: dict[str, CapabilityState] = {}
    if isinstance(caps_raw, dict):
        for cap_id, cap_raw in caps_raw.items():
            if not isinstance(cap_raw, dict):
                continue
            try:
                caps[str(cap_id)] = CapabilityState(
                    current_level=int(cap_raw.get("current_level", 1)),
                    runs_total=int(cap_raw.get("runs_total", 0)),
                    runs_at_current_level=int(
                        cap_raw.get("runs_at_current_level", 0)
                    ),
                    last_score=_optional_float(cap_raw.get("last_score")),
                    last_run_at=_optional_str(cap_raw.get("last_run_at")),
                )
            except (TypeError, ValueError):
                # Corrupt row — drop just this capability; the next
                # ``record_capability_run`` will rebuild it from
                # scratch at level 1.
                continue
    return SkillState(
        schema=STATE_SCHEMA,
        skill_id=str(raw.get("skill_id") or ""),
        skill_version=str(raw.get("skill_version") or ""),
        capabilities=caps,
    )


def save_state(skill_folder: Path, state: SkillState) -> None:
    """Write ``state.yaml`` atomically (write to .tmp + rename)."""
    payload = {
        "schema": state.schema,
        "skill_id": state.skill_id,
        "skill_version": state.skill_version,
        "capabilities": {
            cap_id: {
                "current_level": cap.current_level,
                "runs_total": cap.runs_total,
                "runs_at_current_level": cap.runs_at_current_level,
                "last_score": cap.last_score,
                "last_run_at": cap.last_run_at,
            }
            for cap_id, cap in state.capabilities.items()
        },
    }
    skill_folder.mkdir(parents=True, exist_ok=True)
    target = state_path(skill_folder)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    tmp.replace(target)


def append_run(skill_folder: Path, run: RunRecord) -> None:
    """Append one ``history.jsonl`` line.  Idempotent in the sense
    that re-appending the same dict is harmless — callers control
    de-duplication."""
    skill_folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": run.ts,
        "cap": run.cap,
        "score": run.score,
        "passed": run.passed,
        "total": run.total,
    }
    if run.artifact:
        payload["artifact"] = run.artifact
    with history_path(skill_folder).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def recent_runs(
    skill_folder: Path,
    *,
    cap_id: str,
    limit: int,
) -> list[RunRecord]:
    """Read the last ``limit`` runs for ``cap_id`` from
    ``history.jsonl``, newest first.  Returns ``[]`` if no history."""
    path = history_path(skill_folder)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[RunRecord] = []
    # Walk newest-first.
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("cap") != cap_id:
            continue
        out.append(RunRecord(
            ts=str(obj.get("ts") or ""),
            cap=str(obj["cap"]),
            score=float(obj.get("score") or 0.0),
            passed=int(obj.get("passed") or 0),
            total=int(obj.get("total") or 0),
            artifact=obj.get("artifact"),
        ))
        if len(out) >= limit:
            break
    return out


# ─── core scoring loop ───────────────────────────────────────────────


def record_capability_run(
    *,
    skill_folder: Path,
    manifest: Manifest,
    cap_id: str,
    score: float,
    passed: int,
    total: int,
    artifact: str | None = None,
    now: float | None = None,
) -> tuple[CapabilityState, int]:
    """Record one scored run for a capability and apply the promotion
    / demotion logic.  Returns the updated ``CapabilityState`` and the
    level *delta* (-1 / 0 / +1) so the caller can log a promotion if
    they want.

    The promotion rule (per the spec): a capability promotes one
    level when its last ``PROMOTION_WINDOW`` runs all scored above
    the *next* band's threshold.  Demotion is symmetric — last
    ``DEMOTION_WINDOW`` runs all below the current band's floor.
    """
    cap = _capability_by_id(manifest, cap_id)
    state = load_state(skill_folder) or SkillState(
        skill_id=manifest.id,
        skill_version=manifest.version,
    )
    state.skill_id = manifest.id
    state.skill_version = manifest.version
    cap_state = state.capabilities.get(cap_id) or CapabilityState(
        current_level=cap.level.current,
    )

    ts = _iso_now(now)
    run = RunRecord(
        ts=ts, cap=cap_id, score=score, passed=passed, total=total,
        artifact=artifact,
    )
    append_run(skill_folder, run)

    cap_state.last_score = score
    cap_state.last_run_at = ts
    cap_state.runs_total += 1
    cap_state.runs_at_current_level += 1

    delta = _apply_level_change(skill_folder, cap, cap_state)
    state.capabilities[cap_id] = cap_state
    save_state(skill_folder, state)
    return cap_state, delta


def _apply_level_change(
    skill_folder: Path,
    cap: Capability,
    cap_state: CapabilityState,
) -> int:
    """Compute the level delta from history and mutate
    ``cap_state.current_level`` in-place.  Returns -1, 0, or +1."""
    bands = cap.level.bands
    max_level = cap.level.max
    current = cap_state.current_level

    # Promotion gate.
    if current < max_level:
        threshold = bands[current]  # the band that promotes us to current+1
        recent = recent_runs(skill_folder, cap_id=cap.id, limit=PROMOTION_WINDOW)
        if (
            len(recent) >= PROMOTION_WINDOW
            and all(r.score >= threshold for r in recent)
        ):
            cap_state.current_level = current + 1
            cap_state.runs_at_current_level = 0
            return 1

    # Demotion gate.  ``current_floor`` is the band that admitted us
    # to the current level — falling below it for the demotion window
    # means we've regressed.
    if current > 1:
        floor = bands[current - 1]
        recent = recent_runs(skill_folder, cap_id=cap.id, limit=DEMOTION_WINDOW)
        if (
            len(recent) >= DEMOTION_WINDOW
            and all(r.score < floor for r in recent)
        ):
            cap_state.current_level = current - 1
            cap_state.runs_at_current_level = 0
            return -1

    return 0


def record_benchmark_result(
    *,
    skill_folder: Path,
    benchmark_payload: dict[str, Any],
    artifact: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Convert one ``benchmark.py`` JSON output into capability state.

    Routing rules:
      * If the payload has a ``cap`` (or ``cap_id``) string, target
        that capability.
      * Else, if the manifest has exactly one capability, target it
        (covers legacy stubs, where the single ``legacy`` capability
        absorbs the whole-skill benchmark).
      * Else, return ``{"ok": False, "reason": "ambiguous"}`` and
        DON'T record — the skill author must add a ``cap`` field
        to disambiguate.

    Returns ``{"ok": bool, "cap": str?, "level": int?, "delta": int?,
    "reason": str?}``.  Never raises — benchmark recording must not
    crash the caller.
    """
    from jaeger_ai.agent.skill_registry.manifest_v3 import load_manifest_from_folder

    try:
        manifest = load_manifest_from_folder(skill_folder)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"manifest load failed: {exc}"}
    if manifest is None:
        return {"ok": False, "reason": "no v3 manifest in skill folder"}

    cap_id = benchmark_payload.get("cap") or benchmark_payload.get("cap_id")
    if not cap_id:
        if len(manifest.capabilities) == 1:
            cap_id = manifest.capabilities[0].id
        else:
            return {
                "ok": False,
                "reason": "benchmark payload has no 'cap' field and the "
                          "manifest declares >1 capability",
            }

    try:
        cap_state, delta = record_capability_run(
            skill_folder=skill_folder,
            manifest=manifest,
            cap_id=str(cap_id),
            score=float(benchmark_payload.get("score", 0.0) or 0.0),
            passed=int(benchmark_payload.get("passed", 0) or 0),
            total=int(benchmark_payload.get("total", 0) or 0),
            artifact=artifact,
            now=now,
        )
    except KeyError as exc:
        return {"ok": False, "reason": str(exc)}

    return {
        "ok": True,
        "cap": cap_id,
        "level": cap_state.current_level,
        "delta": delta,
        "runs_total": cap_state.runs_total,
    }


def _capability_by_id(manifest: Manifest, cap_id: str) -> Capability:
    for cap in manifest.capabilities:
        if cap.id == cap_id:
            return cap
    raise KeyError(
        f"capability {cap_id!r} not declared on skill {manifest.id!r}"
    )


# ─── helpers ─────────────────────────────────────────────────────────


def _iso_now(now: float | None = None) -> str:
    """Wall-clock UTC timestamp in ISO 8601 with second precision.
    Callers can pass an explicit ``now`` (e.g. in tests) for
    reproducibility."""
    if now is None:
        now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def _optional_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _optional_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
