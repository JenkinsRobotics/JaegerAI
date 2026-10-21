"""GB-025 error oracle: when the secure sandbox is unavailable, execution is refused with the exact
boundary reason and nothing runs; protections are not disabled to make the call succeed."""
from __future__ import annotations

from jaeger_agent.tools import code


def test_unavailable_sandbox_refuses_without_running(tmp_path, monkeypatch):
    marker = tmp_path / "escaped.txt"
    monkeypatch.setattr(code, "_sandboxed_python_command", lambda *a, **k: (None, "linux-bwrap-unavailable: fixture"))
    ran = []
    monkeypatch.setattr(code, "run_interruptible", lambda *a, **k: ran.append(a))
    result = code.run_python(f"open({str(marker)!r}, 'w').write('x')")
    assert result["ok"] is False
    assert result["error_type"] == "sandbox_unavailable" and result["retryable"] is False
    assert result["sandbox_backend"] == "linux-bwrap-unavailable: fixture"
    assert ran == [] and not marker.exists()
