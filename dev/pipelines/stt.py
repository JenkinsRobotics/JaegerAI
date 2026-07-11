#!/usr/bin/env python3
"""STT pipeline probe (Voice in · ASR).

Bench the swappable STT methods on a clip — delegates to the STT method
bench (nodes/whisper_stt/engine).

    .venv/bin/python dev/pipelines/stt.py clip.wav [--method all] [--ref "what was said"]
    .venv/bin/python dev/pipelines/stt.py --record 5 --method two_pass
    .venv/bin/python dev/pipelines/stt.py --list
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from jaeger_os.nodes.whisper_stt.engine.bench import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
