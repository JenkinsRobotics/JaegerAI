"""Launch or preflight JaegerAI's multimodal face."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from types import SimpleNamespace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JaegerAI multimodal face")
    parser.add_argument("--check", action="store_true", help="check models and devices")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the model/audio-free Event routing test",
    )
    parser.add_argument(
        "--audio",
        choices=("plain", "structured", "quasi", "full"),
        default="structured",
        help="initial audio pipeline (plain is CLI-only)",
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="attach this face to the already-running native app agent",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="boot an isolated runtime (benchmark/development only)",
    )
    args = parser.parse_args(argv)
    if args.check:
        from .preflight import check

        return check(audio_mode=args.audio)
    if args.selftest:
        from .selftest import main as selftest_main

        return selftest_main()
    os.environ["JAEGER_MULTIMODAL_AUDIO_MODE"] = args.audio
    if not args.standalone:
        from PySide6.QtWidgets import QApplication

        from .remote_runtime import AttachedAgentRuntime
        from .window import MultimodalWindow

        app = QApplication.instance() or QApplication([])
        from ..branding import apply_app_identity

        apply_app_identity()
        runtime = AttachedAgentRuntime()
        ctx = SimpleNamespace(core=SimpleNamespace(runtime=runtime), bus=None)
        window = MultimodalWindow(ctx, main_surface=True)
        window.show()
        try:
            return int(app.exec())
        finally:
            runtime.close()
    from jaeger_os.app import JaegerApp

    manifest = Path(__file__).resolve().parents[4] / "jaeger.multimodal.toml"
    return JaegerApp(manifest).run()


if __name__ == "__main__":
    raise SystemExit(main())
