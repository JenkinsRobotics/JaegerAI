"""Capability → ToolDef registration — hardware becomes ordinary tools.

Topology capabilities (``motion.move_joints``, ``lights.set_mode``…)
group by their first segment into per-subsystem **umbrella tools**
(``motion(action=…)``, ``lights(action=…)``) following the repo's
kanban/memory/skill precedent — the agent sees a handful of tools, not
one per verb (plan §2.6/§3.5).

Per-call flow inside an umbrella dispatcher:

  1. permission check — the capability's tier through the live
     ``PermissionPolicy`` (HARDWARE now rides the confirmation flow);
  2. e-stop — fail closed while latched, unless the capability is
     marked ``allow_when_latched`` (``motion.stop`` must work DURING
     a latch — it's the agent-reachable stop);
  3. link health — controller offline → typed retryable error;
  4. per-action Pydantic validation against the capability's own
     schema (the umbrella's merged model is documentation; the
     action's model is the trust boundary);
  5. handler call with a :class:`CapabilityContext`.

Nothing in here raises into the agent loop — every failure path
returns the loop's typed error-result contract
(``{"ok": false, "error": …, "retryable": …}``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

from jaeger_os.agent.schemas.tool_registry import register_tool_instance
from jaeger_os.agent.schemas.tool_schema import ToolDef
from jaeger_os.core.safety.permissions import (
    PermissionError as TierError,
    PermissionRequest,
    PermissionTier,
    current_policy,
)

from .link import Link
from .package import CapabilitySpec, ControllerSpec, PackageSpec, resolve_ref
from .safety import EStopLatch


@dataclass
class CapabilityContext:
    """What a capability handler receives alongside its validated args."""
    package: str
    controller: str                  # controller key this action targets
    link: Link | None                # that controller's link ("*" caps: None)
    links: dict[str, Link]           # every link in the package, by key
    controllers: dict[str, ControllerSpec]
    estop: EStopLatch | None


@dataclass
class _Action:
    cap: CapabilitySpec
    tier: PermissionTier
    schema: type[BaseModel]
    handler: Any
    refuses_when_latched: bool


def _split_name(name: str) -> tuple[str, str]:
    umbrella, _, action = name.partition(".")
    if not action:
        raise ValueError(
            f"capability {name!r} must be 'subsystem.action' "
            "(e.g. 'motion.move_joints')"
        )
    return umbrella, action.replace(".", "_")


def _resolve_handler(cap: CapabilitySpec, *, package: str) -> Any:
    """Explicit ``handler:`` ref wins; otherwise the convention: a
    function named after the action, in the schema's module
    (``jp01.capabilities:MoveJointsArgs`` + ``motion.move_joints`` →
    ``jp01.capabilities:move_joints``)."""
    if cap.handler:
        return resolve_ref(cap.handler, package=package)
    schema_mod = cap.schema.partition(":")[0]
    _, action = _split_name(cap.name)
    return resolve_ref(f"{schema_mod}:{action}", package=package)


def _merge_args_model(
    umbrella: str, actions: dict[str, _Action],
) -> type[BaseModel]:
    """One documentation-grade model for the umbrella: a required
    ``action`` literal plus every action field, optional. Same field
    name with conflicting annotations across actions refuses loudly —
    rename in the package rather than ship an ambiguous schema."""
    fields: dict[str, Any] = {
        "action": (
            Literal[tuple(sorted(actions))],  # type: ignore[valid-type]
            Field(description="Which operation to perform."),
        ),
    }
    seen: dict[str, Any] = {}
    for action_name, act in sorted(actions.items()):
        for fname, finfo in act.schema.model_fields.items():
            ann = finfo.annotation
            if fname in seen:
                if seen[fname] != ann:
                    raise ValueError(
                        f"umbrella {umbrella!r}: field {fname!r} has "
                        f"conflicting types across actions "
                        f"({seen[fname]} vs {ann} in {action_name!r})"
                    )
                continue
            seen[fname] = ann
            fields[fname] = (
                Optional[ann],
                Field(default=None, description=finfo.description or ""),
            )
    return create_model(  # type: ignore[call-overload]
        f"{umbrella.title().replace('_', '')}UmbrellaArgs",
        __config__=ConfigDict(arbitrary_types_allowed=True),
        **fields,
    )


def _umbrella_description(umbrella: str, actions: dict[str, _Action]) -> str:
    lines = [f"Robot {umbrella} control. Pick an action; pass only that "
             "action's arguments."]
    for action_name, act in sorted(actions.items()):
        desc = act.cap.description or act.schema.__doc__ or ""
        lines.append(f"- {action_name} ({act.tier.name}): {desc.strip()}")
    return "\n".join(lines)


def _offline_error(controller: str, link: Link | None) -> dict[str, Any]:
    detail = ""
    if link is not None:
        detail = link.last_error or "link not connected"
    return {
        "ok": False,
        "error": f"{controller} offline — {detail or 'no link'}",
        "retryable": True,
    }


def _make_dispatcher(
    umbrella: str,
    actions: dict[str, _Action],
    ctx_base: dict[str, Any],
):
    """Build the umbrella's handler fn. Signature is ``**kwargs``
    because the registry validates against the merged model before
    dispatch; the per-action model re-validates inside."""

    def dispatch(**kwargs: Any) -> dict[str, Any]:
        action_name = kwargs.pop("action", "")
        act = actions.get(str(action_name))
        if act is None:
            return {
                "ok": False,
                "error": f"unknown action {action_name!r} for {umbrella}; "
                         f"valid: {sorted(actions)}",
                "retryable": False,
            }

        # 1. Permission tier.
        try:
            current_policy().check(PermissionRequest(
                tier=act.tier,
                skill=f"hardware.{ctx_base['package']}",
                operation=act.cap.name,
                summary=act.cap.description,
            ))
        except TierError as exc:
            return {"ok": False, "error": str(exc), "retryable": False}

        # 2. E-stop latch — fail closed.
        estop: EStopLatch | None = ctx_base.get("estop")
        if estop is not None and estop.engaged and act.refuses_when_latched:
            return {"ok": False, "error": estop.refusal(), "retryable": False}

        # 3. Link health.
        links: dict[str, Link] = ctx_base["links"]
        link = links.get(act.cap.controller)
        if act.cap.controller != "*" and (link is None or not link.connected):
            return _offline_error(act.cap.controller, link)

        # 4. Per-action validation (drop the merged model's Nones —
        #    they're just fields belonging to sibling actions).
        provided = {k: v for k, v in kwargs.items() if v is not None}
        try:
            args = act.schema.model_validate(provided)
        except Exception as exc:  # noqa: BLE001 — pydantic error → typed result
            return {
                "ok": False,
                "error": f"invalid arguments for {act.cap.name}: {exc}",
                "retryable": False,
            }

        # 5. Handler.
        ctx = CapabilityContext(
            package=ctx_base["package"],
            controller=act.cap.controller,
            link=link,
            links=links,
            controllers=ctx_base["controllers"],
            estop=estop,
        )
        try:
            result = act.handler(ctx, args)
        except Exception as exc:  # noqa: BLE001 — hardware faults stay typed
            return {
                "ok": False,
                "error": f"{act.cap.name} failed: {exc}",
                "retryable": True,
            }
        if isinstance(result, dict):
            result.setdefault("ok", True)
            return result
        return {"ok": True, "result": result}

    dispatch.__name__ = umbrella
    dispatch.__doc__ = f"Umbrella dispatcher for {umbrella} capabilities."
    return dispatch


def register_package_capabilities(
    spec: PackageSpec,
    *,
    links: dict[str, Link],
    estop: EStopLatch | None = None,
) -> list[ToolDef]:
    """Register one beta-gated umbrella tool per capability subsystem.

    Returns the created ToolDefs (callers keep them for boot logs /
    teardown). Refuses loudly — unknown tier names, unresolvable
    schema/handler refs, conflicting field types — so a broken package
    fails at load, not mid-mission.
    """
    estop_scope = set(spec.safety.estop_scope) if spec.safety else set()

    grouped: dict[str, dict[str, _Action]] = {}
    for cap in spec.capabilities:
        umbrella, action = _split_name(cap.name)
        try:
            tier = PermissionTier[cap.tier]
        except KeyError:
            raise ValueError(
                f"capability {cap.name!r}: unknown tier {cap.tier!r}; "
                f"valid: {[t.name for t in PermissionTier]}"
            ) from None
        schema = resolve_ref(cap.schema, package=spec.package)
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                f"capability {cap.name!r}: schema ref {cap.schema!r} is "
                "not a Pydantic BaseModel"
            )
        # Only HARDWARE-tier actions refuse during a latch — telemetry
        # reads and light control must keep working while stopped
        # (you WANT eyes and a red flash during an e-stop). motion.stop
        # opts out via allow_when_latched: it IS the stop.
        grouped.setdefault(umbrella, {})[action] = _Action(
            cap=cap,
            tier=tier,
            schema=schema,
            handler=_resolve_handler(cap, package=spec.package),
            refuses_when_latched=(
                tier == PermissionTier.HARDWARE
                and not cap.allow_when_latched
                and (cap.controller in estop_scope or cap.controller == "*")
            ),
        )

    ctx_base = {
        "package": spec.package,
        "links": links,
        "controllers": spec.controllers,
        "estop": estop,
    }

    defs: list[ToolDef] = []
    for umbrella, actions in grouped.items():
        controllers = {
            a.cap.controller for a in actions.values()
            if a.cap.controller != "*"
        }

        def _available(_c: frozenset[str] = frozenset(controllers)) -> bool:
            if not _c:   # "*"-only umbrellas ride on any live link
                return any(lk.connected for lk in links.values())
            return any(
                lk.connected for k, lk in links.items() if k in _c
            )

        tiers = [a.tier for a in actions.values()]
        tool = ToolDef(
            name=umbrella,
            description=_umbrella_description(umbrella, actions),
            args_model=_merge_args_model(umbrella, actions),
            fn=_make_dispatcher(umbrella, actions, ctx_base),
            dangerous=any(t == PermissionTier.HARDWARE for t in tiers),
            beta=True,   # visible only under JAEGER_DEV_MODE until walked
            toolset="hardware",
            permission_tier=max(tiers).name,
            side_effect=(
                "hardware"
                if any(t == PermissionTier.HARDWARE for t in tiers)
                else "read"
                if all(t == PermissionTier.READ_ONLY for t in tiers)
                else ""
            ),
            check_fn=_available,
        )
        register_tool_instance(tool)
        defs.append(tool)
    return defs


__all__ = ["CapabilityContext", "register_package_capabilities"]
