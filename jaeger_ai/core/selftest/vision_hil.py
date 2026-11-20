"""Physical camera, image recognition, and temporal video understanding verification (§4.1-§4.3).

Separates:
  - Physical camera capture (Insta360 Link 2 via AVFoundation/OpenCV — never faked with synthetic frames)
  - Deterministic known image fixtures + local vision LLM ground truth
  - Deterministic temporal video fixture decoding + motion + ordered event sequence understanding
"""
from __future__ import annotations

import io
from pathlib import Path
import time
from typing import Any

import numpy as np

from jaeger_ai.core.models import local_vision
from .models import CheckResult, CheckStatus


def enumerate_cameras() -> dict[str, Any]:
    out: dict[str, Any] = {"cameras": [], "tcc_camera_status": None}
    try:
        import AVFoundation
        out["tcc_camera_status"] = int(
            AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeVideo)
        )
        devs = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
        for i, d in enumerate(devs):
            out["cameras"].append({"index": i, "name": str(d.localizedName()), "id": str(d.uniqueID())})
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def capture_live_camera_frames(
    *,
    preferred_name: str = "Insta360 Link 2",
    num_frames: int = 8,
    artifacts_dir: Path,
) -> dict[str, Any]:
    """Open the real physical camera and capture sequential frames with integrity checks."""
    import cv2

    cam_info = enumerate_cameras()
    cameras = cam_info.get("cameras") or []
    tcc = cam_info.get("tcc_camera_status")
    if tcc not in (None, 3):
        return {"ok": False, "blocked": True, "reason": f"macOS Camera TCC permission not granted (status={tcc})", "cameras": cameras}
    if not cameras:
        return {"ok": False, "blocked": True, "reason": "No physical camera enumerated by AVFoundation", "cameras": cameras}

    # Prefer physical Insta360 Link 2 (not virtual camera)
    chosen_idx = 0
    chosen_name = cameras[0]["name"]
    for c in cameras:
        if preferred_name.lower() in c["name"].lower() and "virtual" not in c["name"].lower():
            chosen_idx = c["index"]
            chosen_name = c["name"]
            break

    cap = cv2.VideoCapture(chosen_idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        return {"ok": False, "blocked": True, "reason": f"Could not open camera index {chosen_idx} ({chosen_name})", "cameras": cameras}

    frames: list[np.ndarray] = []
    timestamps: list[float] = []
    dropped = 0
    try:
        # Warmup 4 frames for auto-exposure / gimbal wake
        for _ in range(4):
            cap.read()
            time.sleep(0.08)
        for _ in range(num_frames):
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                frames.append(frame)
                timestamps.append(time.time())
            else:
                dropped += 1
            time.sleep(0.06)
    finally:
        cap.release()

    if not frames:
        return {"ok": False, "blocked": True, "reason": f"Camera '{chosen_name}' returned 0 readable frames", "dropped": dropped}

    h, w = frames[-1].shape[:2]
    means = [float(np.mean(f)) for f in frames]
    stds = [float(np.std(f)) for f in frames]
    diffs = [float(np.mean(np.abs(frames[i].astype(np.float32) - frames[i - 1].astype(np.float32)))) for i in range(1, len(frames))]
    is_black = max(means) < 3.0 and max(stds) < 2.0
    is_frozen = bool(diffs) and max(diffs) == 0.0

    sample_path = artifacts_dir / "live_camera_frame.png"
    cv2.imwrite(str(sample_path), frames[-1])
    monotonic_ts = all(timestamps[i] >= timestamps[i - 1] for i in range(1, len(timestamps)))

    return {
        "ok": (not is_black) and monotonic_ts,
        "camera_name": chosen_name,
        "camera_index": chosen_idx,
        "resolution": [int(w), int(h)],
        "captured_frames": len(frames),
        "dropped_frames": dropped,
        "monotonic_timestamps": monotonic_ts,
        "mean_luma": round(means[-1], 2),
        "std_luma": round(stds[-1], 2),
        "max_interframe_diff": round(max(diffs), 3) if diffs else 0.0,
        "black_frame": is_black,
        "frozen_stream": is_frozen,
        "sample_path": str(sample_path),
        "frame_png_bytes": sample_path.read_bytes(),
    }


def run_camera_capture_check(*, artifacts_dir: Path, model: str = "qwen3.5:9b") -> CheckResult:
    """§4.1 Real physical camera capture + local vision routing check."""
    t0 = time.perf_counter()
    cap = capture_live_camera_frames(artifacts_dir=artifacts_dir)
    if cap.get("blocked"):
        return CheckResult(
            id="camera_capture",
            name="Physical camera capture (Insta360 Link 2) + vision routing",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=str(cap.get("reason") or "camera blocked"),
        )
    if not cap.get("ok"):
        return CheckResult(
            id="camera_capture",
            name="Physical camera capture (Insta360 Link 2) + vision routing",
            status=CheckStatus.FAIL,
            elapsed_s=round(time.perf_counter() - t0, 2),
            metrics={k: v for k, v in cap.items() if k != "frame_png_bytes"},
            reason="Camera returned black frames or non-monotonic timestamps",
        )

    vis = local_vision.describe(
        cap["frame_png_bytes"],
        "Briefly describe what is visible in this live webcam frame in one or two factual sentences. Do not invent objects you cannot see.",
        model=model,
        timeout=90,
    )
    ok = bool(cap["ok"] and vis.get("ok") and len(str(vis.get("answer") or "")) >= 10)
    return CheckResult(
        id="camera_capture",
        name="Physical camera capture (Insta360 Link 2) + vision routing",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "camera": cap["camera_name"],
            "resolution": cap["resolution"],
            "captured_frames": cap["captured_frames"],
            "dropped_frames": cap["dropped_frames"],
            "mean_luma": cap["mean_luma"],
            "max_interframe_diff": cap["max_interframe_diff"],
            "black_frame": cap["black_frame"],
            "frozen_stream": cap["frozen_stream"],
            "vision_model": vis.get("model"),
            "vision_elapsed_s": vis.get("elapsed_s"),
        },
        evidence={"vision_description": vis.get("answer"), "sample_path": cap["sample_path"]},
        reason="" if ok else str(vis.get("error") or "vision description failed"),
    )


def _generate_known_image_fixture() -> bytes:
    """Generate a deterministic 640x480 fixture with shapes, colors, spatial layout, and text."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(img)
    # Left: red circle; Right: blue square; Bottom center: green triangle + text "TRUTH 47"
    draw.ellipse((40, 60, 220, 240), fill=(220, 30, 30))
    draw.rectangle((420, 60, 600, 240), fill=(30, 70, 220))
    draw.polygon([(320, 260), (240, 370), (400, 370)], fill=(30, 175, 60))

    font = None
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            font = ImageFont.truetype(name, 56)
            break
        except OSError:
            continue
    draw.text((185, 395), "TRUTH 47", fill="black", font=font or ImageFont.load_default())
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_image_recognition_check(*, artifacts_dir: Path, model: str = "qwen3.5:9b") -> CheckResult:
    """§4.2 Deterministic image fixture (colors, shapes, text, numbers, spatial relations) + vision LLM."""
    t0 = time.perf_counter()
    from PIL import Image

    png_bytes = _generate_known_image_fixture()
    out_path = artifacts_dir / "known_image_fixture.png"
    out_path.write_bytes(png_bytes)

    # Deterministic pixel sanity verification
    arr = np.array(Image.open(io.BytesIO(png_bytes)))
    left_px = arr[150, 130]   # red circle center
    right_px = arr[150, 510]  # blue square center
    det_ok = bool(left_px[0] > 180 and left_px[2] < 80 and right_px[2] > 180 and right_px[0] < 80)

    vis = local_vision.describe(
        png_bytes,
        "State: (1) what shape and color is on the left, (2) what shape and color is on the right, "
        "(3) what color is the triangle, and (4) the exact word and number written at the bottom.",
        model=model,
        timeout=90,
    )
    ans = str(vis.get("answer") or "").lower()
    checks = {
        "deterministic_pixels": det_ok,
        "red_circle": ("red" in ans and "circle" in ans),
        "blue_square": ("blue" in ans and "square" in ans),
        "green_triangle": ("green" in ans and "triangle" in ans),
        "text_truth_47": ("truth" in ans and "47" in ans),
        "spatial_left_right": ("left" in ans and "right" in ans),
    }
    passed = bool(vis.get("ok") and all(checks.values()))
    return CheckResult(
        id="image_recognition",
        name="Known image fixture recognition (shapes, colors, text, numbers, spatial)",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={"checks": checks, "model": vis.get("model"), "vision_elapsed_s": vis.get("elapsed_s")},
        evidence={"answer": vis.get("answer"), "fixture_path": str(out_path)},
        reason="" if passed else f"Failed ground-truth checks: {[k for k, v in checks.items() if not v]}",
    )


def run_video_understanding_check(*, artifacts_dir: Path, model: str = "qwen3.5:9b") -> CheckResult:
    """§4.3 Synthetic temporal video decoding, motion tracking, frame extraction, and event order."""
    t0 = time.perf_counter()
    import cv2
    from PIL import Image

    video_path = artifacts_dir / "temporal_fixture.mp4"
    w, h, fps = 480, 270, 10
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (w, h))
    if not writer.isOpened():
        return CheckResult(
            id="video_understanding",
            name="Temporal video decoding, motion & ordered event understanding",
            status=CheckStatus.FAIL,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="OpenCV VideoWriter failed to open mp4v output",
        )

    # 30 frames (3 seconds): moving object + 3 distinct ordered color/label phases
    phases = [
        ("T=0s STEP 1 RED", (30, 30, 220)),     # BGR red
        ("T=1s STEP 2 GREEN", (40, 190, 40)),   # BGR green
        ("T=2s STEP 3 BLUE", (220, 70, 30)),    # BGR blue
    ]
    for f_idx in range(30):
        frame = np.full((h, w, 3), 245, dtype=np.uint8)
        phase_idx = f_idx // 10
        label, bgr = phases[phase_idx]
        cx = int(70 + (f_idx / 29.0) * (w - 140))
        cy = h // 2 + 20
        cv2.circle(frame, (cx, cy), 34, bgr, -1)
        cv2.putText(frame, label, (25, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (15, 15, 15), 2, cv2.LINE_AA)
        cv2.putText(frame, f"frame={f_idx:02d}", (25, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 60), 2, cv2.LINE_AA)
        writer.write(frame)
    writer.release()

    # Decode video & verify frame continuity + motion
    cap = cv2.VideoCapture(str(video_path))
    decoded: list[np.ndarray] = []
    while True:
        ok_r, fr = cap.read()
        if not ok_r or fr is None:
            break
        decoded.append(fr)
    cap.release()

    if len(decoded) < 25:
        return CheckResult(
            id="video_understanding",
            name="Temporal video decoding, motion & ordered event understanding",
            status=CheckStatus.FAIL,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"Expected 30 decoded frames, got {len(decoded)}",
        )

    motion_scores = [
        float(np.mean(np.abs(decoded[i].astype(np.float32) - decoded[i - 1].astype(np.float32))))
        for i in range(1, len(decoded))
    ]
    motion_detected = float(np.mean(motion_scores)) > 0.5

    # Extract 3 ordered keyframes (frames 2, 15, 27) and build labeled horizontal filmstrip for VLM sequence check
    kf_indices = [2, len(decoded) // 2, len(decoded) - 3]
    strip_bgr = np.hstack([decoded[i] for i in kf_indices])
    strip_rgb = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(strip_rgb).save(buf, format="PNG")
    strip_bytes = buf.getvalue()
    (artifacts_dir / "temporal_keyframes.png").write_bytes(strip_bytes)

    vis = local_vision.describe(
        strip_bytes,
        "These three frames are in chronological order from left to right (Step 1, Step 2, Step 3). "
        "State the color sequence of the circle in order and which direction the circle moves across the frames.",
        model=model,
        timeout=90,
    )
    ans = str(vis.get("answer") or "").lower()
    r_pos, g_pos, b_pos = ans.find("red"), ans.find("green"), ans.find("blue")
    order_ok = (r_pos != -1 and g_pos != -1 and b_pos != -1 and r_pos < g_pos < b_pos)
    motion_ans_ok = ("left to right" in ans) or ("right" in ans)
    passed = bool(vis.get("ok") and motion_detected and order_ok and motion_ans_ok)

    return CheckResult(
        id="video_understanding",
        name="Temporal video decoding, motion & ordered event understanding",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "decoded_frames": len(decoded),
            "mean_motion_diff": round(float(np.mean(motion_scores)), 3),
            "motion_detected": motion_detected,
            "color_order_ok": order_ok,
            "motion_direction_ok": motion_ans_ok,
            "vision_elapsed_s": vis.get("elapsed_s"),
        },
        evidence={"answer": vis.get("answer"), "video_path": str(video_path)},
        reason="" if passed else f"Temporal check failed (order_ok={order_ok}, motion_ans_ok={motion_ans_ok})",
    )
