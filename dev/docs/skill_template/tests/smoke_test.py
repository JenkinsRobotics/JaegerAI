"""Smoke test for example_v1.

Runs as a subprocess from the skill loader before registration. Must:
  - exit 0 if the skill is healthy
  - exit non-zero (and print to stderr) if anything is broken

Keep smoke tests fast (under a few seconds) — they run at every startup.
"""

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "example", Path(__file__).resolve().parent.parent / "example.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out = mod.say_example("jaeger")
    assert out == {"greeting": "Hello, jaeger!", "skill": "example_v1"}, out
    out2 = mod.say_example()  # default arg
    assert out2["greeting"] == "Hello, world!", out2
    print("example_v1 smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
