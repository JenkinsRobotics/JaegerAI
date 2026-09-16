from __future__ import annotations

import sys
from pathlib import Path


FEATURE_ROOT = Path(__file__).resolve().parents[6] / "jaeger_ai/features/webui"
feature_path = str(FEATURE_ROOT)
if feature_path not in sys.path:
    sys.path.insert(0, feature_path)
