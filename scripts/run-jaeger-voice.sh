#!/bin/zsh
# Realtime voice service (Pipecat WebRTC, Parakeet, Silero + Smart Turn, Phonon, Gemini Live).
# Runs from its own venv so the voice stack never touches Jaeger's main environment:
#   uv venv --python 3.12 ~/.jaeger/voice-venv
#   uv pip install --python ~/.jaeger/voice-venv/bin/python -r jaeger_ai/features/voice/realtime/requirements.txt
set -euo pipefail
ROOT="${JAEGER_INSTALL_ROOT:-$HOME/GitHub/JaegerAI}"
VENV="${JAEGER_VOICE_VENV:-$HOME/.jaeger/voice-venv}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTHONUNBUFFERED=1
exec "$VENV/bin/python" "$ROOT/jaeger_ai/features/voice/realtime/service.py"
