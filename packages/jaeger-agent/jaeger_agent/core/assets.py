"""Small, versioned runtime assets installed with the agent wheel."""
from pathlib import Path

DEFAULT_SILERO_MODEL = (
    Path(__file__).resolve().parents[1] / "assets/silero/silero_vad_16k_op15.onnx"
)
