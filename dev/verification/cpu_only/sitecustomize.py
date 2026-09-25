"""Opt-in test-process guard: never load a neural/GPU backend in this run.

Usage: PYTHONPATH="$PWD/dev/verification/cpu_only:$PWD" python -m pytest ...
Inherited by Python subprocesses; does not affect any other running agent.
"""

import os
import sys
from importlib.abc import MetaPathFinder

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QSG_RHI_BACKEND"] = "software"
os.environ["QT_OPENGL"] = "software"
os.environ["CUDA_VISIBLE_DEVICES"] = ""


class NoNeuralBackends(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root in {"torch", "llama_cpp", "mlx", "mlx_lm", "mlx_vlm", "kokoro",
                    "pywhispercpp", "_pywhispercpp", "tensorflow", "jax", "cupy",
                    "coremltools"}:
            raise RuntimeError(f"CPU-only verification forbids neural backend: {fullname}")


sys.meta_path.insert(0, NoNeuralBackends())
