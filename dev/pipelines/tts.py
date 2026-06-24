#!/usr/bin/env python3
"""TTS pipeline probe (Voice out · TTS).

Boot the Kokoro TTS node and speak a phrase through the bus (the same
/act/speech → /sense/spoken request the agent's speak tool uses).

    .venv/bin/python dev/pipelines/tts.py "hello, this is the TTS probe"
"""

import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main(argv: list[str]) -> int:
    text = " ".join(argv) or "Hello from the Jaeger TTS pipeline probe."
    from jaeger_os.nodes import runtime
    from jaeger_os.transport import topics

    print(f"booting TTS node + speaking: {text!r}")
    try:
        runtime.ensure_tts_node(warm=True)
        bus = runtime.get_bus()
        ack = bus.request(
            topics.SpeechCommand(text=text, node_id="probe",
                                 correlation_id=uuid.uuid4().hex),
            ack_topic=topics.SENSE_SPOKEN, timeout_s=60.0)
        print("spoken ack:", getattr(ack, "ok", None) if ack else "timeout")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("TTS probe error:", type(exc).__name__, exc)
        return 1
    finally:
        try:
            runtime.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
