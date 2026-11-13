"""Input guardrail config applies on the next turn and can be turned off."""
import os
import time

from jaeger_agent import guardrails
from jaeger_ai.core.safety import guardrails as builtin


def _write(path, body):
    path.write_text(body, encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))


def test_input_block_pattern_trips_then_is_removed(tmp_path):
    guardrails.clear()
    cfg = tmp_path / "config.yaml"
    _write(cfg, "guardrails:\n  input:\n    block_patterns: ['rm -rf /']\n")
    assert "input:blocked_pattern" in builtin.install(cfg)
    tripped = guardrails.run("input", "please rm -rf / now")
    assert tripped is not None and tripped.guardrail == "blocked_pattern"
    assert "input guardrail" in guardrails.refusal("input", tripped)

    _write(cfg, "guardrails:\n  input:\n    block_patterns: []\n")
    names = builtin.refresh_if_changed(cfg)
    assert names is not None and "input:blocked_pattern" not in names
    assert guardrails.run("input", "please rm -rf / now") is None
    assert builtin.refresh_if_changed(cfg) is None  # unchanged: no re-install
    guardrails.clear()
