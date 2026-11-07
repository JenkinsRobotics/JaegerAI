"""Owner-only local controls for the droid's voice/video conversation."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time


def paths():
    from jaeger_ai.core.instance.instance import operator_state_root
    root = operator_state_root()
    run = root / "run" / "conversation"
    run.mkdir(parents=True, exist_ok=True, mode=0o700)
    run.chmod(0o700)
    return root, run


def send(action):
    _, run = paths()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        connection.connect(str(run / "control.sock"))
        connection.sendall((action + "\n").encode())
        return json.loads(connection.makefile("rb").readline(65536))


def next_mode(current, action):
    if action == "off":
        return "off"
    if action not in {"voice", "video"}:
        raise ValueError("Expected voice, video, off or status")
    return "off" if current == action else action


def serve():
    root, run = paths()
    lock = (run / "service.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    socket_path = run / "control.sock"
    socket_path.unlink(missing_ok=True)
    process = None
    mode = "off"
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())

    def stop_worker():
        nonlocal process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process = None

    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        server.listen(4)
        server.settimeout(0.5)
        try:
            while not stopped.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(2)
                    try:
                        action = connection.recv(128).decode().strip()
                        if action != "status":
                            if process and process.poll() is None and (run / "status.json").exists():
                                mode = json.loads((run / "status.json").read_text()).get("mode", mode)
                            mode = next_mode(mode if process and process.poll() is None else "off", action)
                            stop_worker()
                            (run / "status.json").unlink(missing_ok=True)
                            if mode != "off":
                                log_dir = root / "logs"
                                log_dir.mkdir(exist_ok=True)
                                with (log_dir / "conversation.log").open("ab") as log:
                                    process = subprocess.Popen(
                                        [sys.executable, "-B", "-m", __package__ + ".control", "worker", "--mode", mode],
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                    )
                        status = {"mode": mode, "state": "off" if mode == "off" else "starting"}
                        if process:
                            if (run / "status.json").exists():
                                status.update(json.loads((run / "status.json").read_text()))
                            if process.poll() is not None:
                                status.update(state="error", mode="off", error=status.get("error") or "Conversation process stopped; see conversation.log")
                        connection.sendall((json.dumps(status) + "\n").encode())
                    except Exception as exc:
                        connection.sendall((json.dumps({"state": "error", "error": str(exc)}) + "\n").encode())
        finally:
            stop_worker()
            socket_path.unlink(missing_ok=True)


def worker(mode):
    root, run = paths()
    config_path = root / "conversation.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    status = {"mode": mode, "state": "starting", "camera": "off"}
    lock = threading.Lock()

    def report(**fields):
        with lock:
            status.update(fields)
            temporary = run / "status.tmp"
            temporary.write_text(json.dumps(status))
            temporary.replace(run / "status.json")

    def shutdown(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    bus = audio = speaker = conversation = vision = None
    audio_thread = None
    try:
        import sounddevice as sd
        from jaeger_os.transport.inproc_bus import InProcBus
        from jaeger_os.nodes.audio_io import make_audio_io_node
        from jaeger_whisper_stt.engine.continuous import WhisperSTTContinuous
        from jaeger_kokoro_tts.engine import KokoroTTS
        from .conversation import Conversation
        from .vision import LocalVision

        input_device = config.get("input_device")
        output_device = config.get("output_device")
        if input_device:
            sd.query_devices(input_device, "input")
        if output_device:
            sd.query_devices(output_device, "output")
        sd.default.device = (input_device, output_device)
        bus = InProcBus()
        audio = make_audio_io_node(bus, {"audio_backend": "sounddevice", "input_device": input_device})
        audio_thread = threading.Thread(target=audio.run, daemon=True)
        audio_thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not audio.health().get("frames_captured"):
            time.sleep(0.1)
        if not audio.health().get("frames_captured"):
            raise RuntimeError("No microphone audio; check device selection and macOS microphone permission")
        duplex = bool(audio.health().get("aec"))
        speaker = KokoroTTS(bus=bus, voice=config.get("voice", "af_heart"))
        report(state="loading speech", duplex=duplex, input_device=input_device, output_device=output_device)
        speaker.warm()
        listener = WhisperSTTContinuous(bus=bus, model_name=config.get("stt_model", "base.en"), phrase_timeout_s=0.6)
        def set_camera(enabled):
            nonlocal vision
            if not enabled:
                if vision:
                    vision.close()
                    vision = None
                report(mode="voice", camera="off")
                return None
            if vision:
                return vision
            model_path = config.get("vision_model_path")
            if not model_path or not Path(model_path).is_dir():
                raise RuntimeError("Video chat needs a cached local Moondream model in conversation.json")
            vision = LocalVision(int(config.get("camera_index", 0)), model_path, report)
            vision.start()
            report(mode="video")
            return vision

        if mode == "video":
            set_camera(True)
        conversation = Conversation(
            listener, speaker, vision=vision, duplex=duplex, report=report,
            set_camera=set_camera, share_visual_context=config.get("share_visual_context") is True,
        )
        conversation.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        report(state="error", error=str(exc))
        return 1
    finally:
        if conversation:
            conversation.close()
        if vision:
            vision.close()
        if speaker:
            speaker.shutdown()
        if audio:
            audio.stop()
        if audio_thread:
            audio_thread.join(timeout=3)
        if bus:
            bus.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["serve", "worker", "voice", "video", "off", "status"])
    parser.add_argument("--mode", choices=["voice", "video"], default="voice")
    args = parser.parse_args()
    if args.action == "serve":
        serve()
        return 0
    if args.action == "worker":
        return worker(args.mode)
    try:
        result = send(args.action)
        print(json.dumps(result, indent=2))
        return int(result.get("state") == "error")
    except (OSError, ValueError) as exc:
        print(f"Conversation control unavailable: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
