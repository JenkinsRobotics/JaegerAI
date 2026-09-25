"""``python -m jaeger_kokoro_tts`` -> the standalone CLI.

The console-script entry point (``jaeger-kokoro-tts``) and this are the
same ``cli.main``; this one works from a source checkout that hasn't
been pip-installed yet.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
