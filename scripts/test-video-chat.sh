#!/usr/bin/env bash
set -euo pipefail

# Find repo root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Ensure venv python
PYTHON_BIN="${HOME}/.jaeger/venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    echo "Error: Python environment not found at $PYTHON_BIN"
    exit 1
fi

echo "======================================================="
echo " Starting JaegerAI Standalone Video & Voice Chat Test  "
echo "======================================================="
echo " - Camera: Insta360 Link 2 (Device 0)"
echo " - Mic: Metal GPU-accelerated Whisper STT"
echo " - Agent: Resident Jaeger Bridge (Iris / Gemma)"
echo " - Audio Output: Kokoro TTS -> UltraFine / System Speakers"
echo "======================================================="

export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/packages/jaeger-kokoro-tts:$REPO_ROOT/packages/jaeger-whisper-stt:${PYTHONPATH:-}"
exec "$PYTHON_BIN" dev/tools/standalone_video_chat.py "$@"
