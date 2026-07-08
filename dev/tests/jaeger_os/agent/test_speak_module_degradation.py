"""0.8 M2a Task B — graceful degradation when kokoro_tts is absent.

``_speak_via_bus`` must not hang for ``_SPEAK_TIMEOUT_S`` (180 s)
waiting on ``bus.request`` when the ``tts`` slot has no discovered
module — it should return the clean "no tts module installed" dict
immediately. This monkeypatches module discovery (the same pattern
``test_tool_availability_wiring.py`` uses for the availability gate)
rather than actually deleting ``jaeger_os/nodes/kokoro_tts/``.

The import guards themselves (``nodes/__init__.py``, ``nodes/
runtime.py``, ``agent/tools/speak.py``, ``core/instance/schemas.py`` —
each wraps its kokoro_tts import in ``try/except ImportError``) are
exercised by inspection plus the fact that every suite in this repo
already imports all four modules successfully with kokoro_tts present
— proving the guards are transparent no-ops on the happy path. A
subprocess harness that actually hides the module was judged not
worth the complexity for this pass.
"""

from __future__ import annotations

import importlib
import time

from jaeger_os.agent import availability as _avail_mod

# ``jaeger_os.agent.tools``'s __init__ does ``from .speak import speak``,
# which rebinds the package attribute ``tools.speak`` to the FUNCTION —
# so both ``from jaeger_os.agent.tools import speak`` and
# ``import jaeger_os.agent.tools.speak as x`` (attribute-access under
# the hood) resolve to that function, not this submodule.
# ``importlib.import_module`` fetches the real module straight out of
# ``sys.modules`` by fully-qualified name, sidestepping the shadowing.
_speak_mod = importlib.import_module("jaeger_os.agent.tools.speak")

_NO_MODULE_RESULT = {"spoken": False, "reason": "no tts module installed"}


def test_speak_via_bus_returns_fast_when_tts_module_missing(monkeypatch):
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    start = time.monotonic()
    result = _speak_mod._speak_via_bus("hello")
    elapsed = time.monotonic() - start
    assert result == _NO_MODULE_RESULT
    assert elapsed < 1.0  # nowhere near the 180s bus.request timeout


def test_speak_returns_fast_when_tts_module_missing(monkeypatch):
    """The public ``speak()`` entrypoint surfaces the same fast, clean
    result (routes through ``_speak_via_bus``)."""
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    start = time.monotonic()
    result = _speak_mod.speak(text="hello")
    elapsed = time.monotonic() - start
    assert result == _NO_MODULE_RESULT
    assert elapsed < 1.0


def test_tts_module_present_true_on_happy_path():
    """Sanity check: with the real kokoro_tts module on disk (as it is
    in this repo today), the presence check is True — the early
    return must NOT fire and existing behavior is unchanged."""
    assert _speak_mod._tts_module_present() is True
