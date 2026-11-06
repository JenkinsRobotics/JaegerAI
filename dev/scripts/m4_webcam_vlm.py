"""M4 webcam perception — capture a frame, understand it with the local MLX VLM.

One command, no UI: opens the first working camera, grabs a frame, runs
moondream2 (mlx-vlm, 4-bit, cached) on it, prints the description and the
measured latency. This is the perception half of "describe a webcam frame in
a voice turn"; the voice turn itself goes through the same Gateway session.

Run:
  PYTHONPATH=. python3 dev/scripts/m4_webcam_vlm.py [--prompt "..."] [--device 0] [--out /tmp/frame.jpg]
"""
from __future__ import annotations

import argparse
import time


def capture_frame(device: int, out: str) -> str:
    import cv2

    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise SystemExit(f"camera index {device} did not open")
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise SystemExit(f"no frame from camera index {device}")
    cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return out


def describe(image_path: str, prompt: str) -> tuple[str, float]:
    from mlx_vlm import generate, load

    t0 = time.time()
    model, processor = load("vikhyatk/moondream2")
    load_s = time.time() - t0
    t0 = time.time()
    out = generate(model, processor, prompt, image=image_path, max_tokens=120, verbose=False)
    infer_s = time.time() - t0
    return f"{out.text}  [model load {load_s:.1f}s, inference {infer_s:.1f}s]", infer_s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--out", default="/tmp/m4_frame.jpg")
    ap.add_argument("--prompt", default="Describe what you see in this image in one sentence.")
    args = ap.parse_args()

    t0 = time.time()
    path = capture_frame(args.device, args.out)
    cap_s = time.time() - t0
    text, infer_s = describe(path, args.prompt)
    print(f"FRAME {path} captured in {cap_s:.2f}s")
    print(f"VLM ({infer_s:.1f}s inference): {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
