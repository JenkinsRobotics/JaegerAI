"""Agent-facing Insta360 Link/Link 2 tools."""

from jaeger_agent.workspace import (
    SandboxError,
    _resolve_under,
    get_effective_workspace_dir,
)
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .link2 import Insta360Link2


def _camera() -> Insta360Link2:
    return Insta360Link2()


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.HARDWARE,
    skill="insta360",
    operation="insta360_status",
    summary="query a physical camera and gimbal",
)
def insta360_status() -> dict:
    """Inspect Insta360 Link/Link 2 video, audio, and gimbal availability."""
    try:
        return {"ok": True, **_camera().status()}
    except (ConnectionError, FileNotFoundError, ImportError, OSError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.HARDWARE,
    skill="insta360",
    operation="insta360_capture",
    summary="activate the camera and capture an image",
)
def insta360_capture(output_path: str = "", resolution: str = "1920x1080") -> dict:
    """Capture one still frame from an Insta360 camera via AVFoundation."""
    try:
        target = _resolve_under(get_effective_workspace_dir(), output_path) if output_path else None
        frame = _camera().capture_frame(
            output_path=target,
            resolution=resolution,
        )
        return {
            "ok": True,
            "path": str(frame.path),
            "width": frame.width,
            "height": frame.height,
            "format": frame.format,
            "timestamp": frame.timestamp,
            "device_name": frame.device_name,
        }
    except (
        ConnectionError,
        FileNotFoundError,
        ImportError,
        OSError,
        RuntimeError,
        SandboxError,
        ValueError,
    ) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.HARDWARE,
    skill="insta360",
    operation="insta360_record_audio",
    summary="activate the microphone and record audio",
)
def insta360_record_audio(duration_seconds: float = 3.0, output_path: str = "") -> dict:
    """Record a bounded microphone sample from an Insta360 camera."""
    if duration_seconds <= 0 or duration_seconds > 300:
        return {"ok": False, "error": "duration_seconds must be between 0 and 300"}
    try:
        target = _resolve_under(get_effective_workspace_dir(), output_path) if output_path else None
        sample = _camera().record_sample(
            duration_seconds=duration_seconds,
            output_path=target,
        )
        return {
            "ok": True,
            "path": str(sample.path),
            "duration_seconds": sample.duration_seconds,
            "sample_rate": sample.sample_rate,
            "channels": sample.channels,
            "format": sample.format,
            "timestamp": sample.timestamp,
            "device_name": sample.device_name,
        }
    except (
        ConnectionError,
        FileNotFoundError,
        ImportError,
        OSError,
        RuntimeError,
        SandboxError,
        ValueError,
    ) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.HARDWARE,
    skill="insta360",
    operation="insta360_aim",
    summary="move the physical camera gimbal",
)
def insta360_aim(pan: int = 0, tilt: int = 0) -> dict:
    """Aim the Insta360 gimbal, clamped to the hardware safety limits."""
    try:
        position = _camera().aim(pan, tilt)
        return {"ok": True, "pan": position.pan, "tilt": position.tilt}
    except (ConnectionError, FileNotFoundError, ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
