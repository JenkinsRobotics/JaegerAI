"""Live personality evals (J-070): runs dev/evals/companion/promptfooconfig.yaml
cases against local Ollama with the same deterministic assertion types promptfoo
uses. llm-rubric asserts are skipped here (promptfoo grades those). Skips when
Ollama or the model is not available — never downloads anything."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pytest
import yaml

from jaeger_ai.features.personality import companion as C
from jaeger_ai.features.personality.character import characters_root, load_character

CFG = Path(__file__).resolve().parents[3] / "evals" / "companion" / "promptfooconfig.yaml"
MODEL = os.environ.get("JAEGER_COMPANION_MODEL", "qwen2.5:3b")  # non-thinking, fast; qwen3:4b leaks reasoning into content


def _have_model() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            return any(m["name"] == MODEL for m in json.load(r)["models"])
    except Exception:  # noqa: BLE001
        return False


CASES = yaml.safe_load(CFG.read_text())["tests"]
pytestmark = [pytest.mark.skipif(not os.environ.get("JAEGER_LIVE_EVALS") or not _have_model(),
                                 reason="set JAEGER_LIVE_EVALS=1 with local Ollama model to run")]


@pytest.mark.parametrize("case", CASES, ids=[c["vars"]["character"] for c in CASES])
def test_personality_case(case):
    v = case["vars"]
    reply = C.chat(load_character(characters_root() / v["character"]), v["message"], model=MODEL)["reply"].lower()
    assert reply
    for a in case["assert"]:
        t, val = a["type"], a["value"]
        if t == "icontains":
            assert val.lower() in reply, reply
        elif t == "not-icontains":
            assert val.lower() not in reply, reply
        elif t == "icontains-any":
            assert any(x.lower() in reply for x in val), reply
