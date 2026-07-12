"""``python -m jaeger_whisper_stt.nodes.whisper_stt.engine`` -> the STT method bench."""

import sys

from .bench import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
