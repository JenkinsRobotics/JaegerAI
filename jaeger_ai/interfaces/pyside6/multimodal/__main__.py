"""Launch or preflight JaegerAI's multimodal face."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JaegerAI multimodal face")
    parser.add_argument("--check", action="store_true", help="check models and devices")
    parser.add_argument(
        "--selftest", action="store_true", help="run the model/audio-free Event routing test"
    )
    parser.add_argument(
        "--audio",
        choices=("plain", "structured", "quasi", "full"),
        default="structured",
        help="initial audio pipeline (plain is CLI-only)",
    )
    args = parser.parse_args(argv)
    if args.check:
        from .preflight import check

        return check(audio_mode=args.audio)
    if args.selftest:
        from .selftest import main as selftest_main

        return selftest_main()
    os.environ["JAEGER_MULTIMODAL_AUDIO_MODE"] = args.audio
    from jaeger_os.app import JaegerApp

    manifest = Path(__file__).resolve().parents[4] / "jaeger.multimodal.toml"
    return JaegerApp(manifest).run()


if __name__ == "__main__":
    raise SystemExit(main())
