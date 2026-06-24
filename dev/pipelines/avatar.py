#!/usr/bin/env python3
"""2D avatar pipeline probe.

Boot the animation node and trigger an expression on it (the agent's
set_avatar_state path). Connect the Swift avatar app (interfaces/avatar/)
or the avatar_player popup to SEE the frames; this probe confirms the
node accepts the command.

    .venv/bin/python dev/pipelines/avatar.py [emotion]      (default: happy)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main(argv: list[str]) -> int:
    emotion = argv[0] if argv else "happy"
    from jaeger_os.nodes import runtime

    try:
        node = runtime.ensure_animation_node(enable_bridge=False)
        print("animation node:", node.state.value)
        from jaeger_os.agent.tools.avatar import set_avatar_state
        result = set_avatar_state(emotion)
        print(f"set_avatar_state({emotion!r}) -> {result}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("avatar probe error:", type(exc).__name__, exc)
        return 1
    finally:
        try:
            runtime.shutdown_animation_node()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
