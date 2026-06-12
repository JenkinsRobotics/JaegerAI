"""JP01 capability arg models + handlers.

Handlers follow the framework convention: function named after the
capability's action, living in this module (the topology's ``schema:``
refs point here too). Each receives ``(ctx: CapabilityContext, args)``
with args already validated against the action's model — the Pydantic
constraints below mirror the firmware clamps, so an out-of-range
command is refused at the tool boundary instead of silently bent on
the wire.

Handlers reach their adapter through :func:`boot.adapter_for` (the
package runtime registry); ``ctx.link`` stays available for raw wire
ops but everything here goes through adapter verbs so the node path
and the capability path share one implementation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from jaeger_os.hardware.capabilities import CapabilityContext

from .adapters.mc01 import (
    JOINT1_RANGE,
    JOINT2_RANGE,
    MAX_DRIVE_DURATION_S,
)


# ── arg models (the per-action trust boundary) ────────────────────────


class EmptyArgs(BaseModel):
    """No arguments."""


class MoveJointsArgs(BaseModel):
    """Servo targets — ranges are the MC01 firmware clamps."""
    a1: int = Field(
        ge=JOINT1_RANGE[0], le=JOINT1_RANGE[1],
        description="Joint 1 angle in degrees (40-150).",
    )
    a2: int = Field(
        ge=JOINT2_RANGE[0], le=JOINT2_RANGE[1],
        description="Joint 2 angle in degrees (70-105).",
    )
    speed: int = Field(
        default=10, ge=1, le=100,
        description="Movement speed percent (default 10, CC01's preview speed).",
    )


class DriveArgs(BaseModel):
    """Drive motor command — duration cap is the firmware's 2 s clamp."""
    s1: int = Field(ge=-100, le=100, description="Left motor percent.")
    s2: int = Field(ge=-100, le=100, description="Right motor percent.")
    duration_s: float = Field(
        default=1.0, gt=0.0, le=MAX_DRIVE_DURATION_S,
        description="Run time in seconds (firmware max 2).",
    )


class LightModeArgs(BaseModel):
    target: Literal["neopixel", "matrix"] = Field(
        description="Which LED surface to address.",
    )
    mode: int = Field(ge=0, le=99, description="Firmware animation mode number (0 = off).")


class LightFrameArgs(BaseModel):
    target: Literal["neopixel", "matrix"] = Field(
        description="Which LED surface to address.",
    )
    frame_hex: str = Field(
        min_length=2, max_length=24576,
        pattern=r"^[0-9a-fA-F]+$",
        description="Raw frame hex: WRGB 8 chars/LED (neopixel) or RGB 6 chars/pixel (matrix).",
    )


class BrightnessArgs(BaseModel):
    value: int = Field(ge=0, le=255, description="Matrix brightness (BM).")


# ── handlers ──────────────────────────────────────────────────────────


def _adapter(ctx: CapabilityContext, controller: str | None = None) -> Any:
    from . import boot
    return boot.adapter_for(controller or ctx.controller)


def move_joints(ctx: CapabilityContext, args: MoveJointsArgs) -> dict:
    sent = _adapter(ctx).move_joints(a1=args.a1, a2=args.a2, speed=args.speed)
    return {"sent": sent}


def drive(ctx: CapabilityContext, args: DriveArgs) -> dict:
    sent = _adapter(ctx).drive(s1=args.s1, s2=args.s2,
                               duration_s=args.duration_s)
    return {"sent": sent, "auto_stop_s": min(args.duration_s,
                                             MAX_DRIVE_DURATION_S)}


def stop(ctx: CapabilityContext, args: EmptyArgs) -> dict:  # noqa: ARG001
    """The agent-reachable emergency stop. Engaging the L2 latch runs
    mc01's registered L1 stop (MM[0,0,0] on the open transport) — one
    write, one path. When already latched (allow_when_latched keeps
    this callable during a latch) the latch won't re-fire L1, so
    re-issue the stop directly: re-stopping is always legal."""
    if ctx.estop is not None and not ctx.estop.engaged:
        ctx.estop.engage("motion.stop capability", source="agent")
    else:
        _adapter(ctx, "mc01").estop()
    return {
        "stopped": True,
        "estop_latched": ctx.estop.engaged if ctx.estop else False,
        "release": "operator action required (estop release)",
    }


def set_mode(ctx: CapabilityContext, args: LightModeArgs) -> dict:
    sent = _adapter(ctx).set_mode(target=args.target, mode=args.mode)
    return {"sent": sent}


def set_frame(ctx: CapabilityContext, args: LightFrameArgs) -> dict:
    sent = _adapter(ctx).set_frame(target=args.target,
                                   frame_hex=args.frame_hex)
    return {"sent": sent, "bytes": len(args.frame_hex) // 2}


def brightness(ctx: CapabilityContext, args: BrightnessArgs) -> dict:
    sent = _adapter(ctx).set_brightness(value=args.value)
    return {"sent": sent}


def status(ctx: CapabilityContext, args: EmptyArgs) -> dict:  # noqa: ARG001
    """Shared by motion.status / lights.status — reports for whichever
    controller the calling capability targets."""
    return _adapter(ctx).telemetry()


def stream_info(ctx: CapabilityContext, args: EmptyArgs) -> dict:  # noqa: ARG001
    return _adapter(ctx, "vcc01").stream_info()


def read(ctx: CapabilityContext, args: EmptyArgs) -> dict:  # noqa: ARG001
    """telemetry.read — every controller's cached snapshot."""
    from . import boot
    runtime = boot.get_runtime()
    if runtime is None:
        return {"ok": False, "error": "jp01 package not booted",
                "retryable": True}
    snapshot = {
        name: adapter.telemetry()
        for name, adapter in runtime.adapters.items()
    }
    if ctx.estop is not None:
        snapshot["estop"] = ctx.estop.status()
    return {"controllers": snapshot}


__all__ = [
    "EmptyArgs", "MoveJointsArgs", "DriveArgs",
    "LightModeArgs", "LightFrameArgs", "BrightnessArgs",
    "move_joints", "drive", "stop", "status",
    "set_mode", "set_frame", "brightness",
    "stream_info", "read",
]
