"""Setup-wizard prompt hardening and model-pick wiring.

Covers three defects found in the first-run walk:

  * every prompt used a bare ``input()``, so Ctrl-D (or any caller that
    spawns setup without a tty) aborted the walk with a raw ``EOFError``;
  * the custom-GGUF prompt returned ``""`` on an empty answer, which made
    the Review screen print a blank model before ``create_instance``
    silently substituted the tier recommendation;
  * the "same as awake" option was gated on the tier RECOMMENDATION rather
    than the operator's actual awake pick, so it disappeared on every tier
    where the awake/asleep recommendations coincide.
"""

import pytest

from jaeger_ai.core.instance import setup_wizard as W


@pytest.fixture(autouse=True)
def _reset_stdin_latch(monkeypatch):
    """The EOF latch is module state; keep it from leaking between tests."""
    monkeypatch.setattr(W, "_STDIN_EXHAUSTED", False, raising=False)
    monkeypatch.delenv(W._NONINTERACTIVE_ENV, raising=False)


def _raise_eof(_prompt):
    raise EOFError


# ── EOF handling ─────────────────────────────────────────────────────


def test_ask_returns_default_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_eof)
    assert W._ask("Agent display name", "Jarvis") == "Jarvis"


def test_ask_yn_returns_default_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_eof)
    assert W._ask_yn("Make default?", True) is True
    monkeypatch.setattr(W, "_STDIN_EXHAUSTED", False, raising=False)
    assert W._ask_yn("Make default?", False) is False


def test_ask_choice_returns_default_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_eof)
    chosen = W._ask_choice("Pick", [("a", "A"), ("b", "B")], default=1)
    assert chosen == "b"


def test_ask_int_returns_default_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_eof)
    assert W._ask_int("How many?", 7) == 7


def test_first_eof_latches_so_later_prompts_do_not_reprompt(monkeypatch):
    """One Ctrl-D must not turn every later question into its own EOFError."""
    calls = []

    def once_then_explode(prompt):
        calls.append(prompt)
        raise EOFError

    monkeypatch.setattr("builtins.input", once_then_explode)
    assert W._ask("first", "a") == "a"
    assert W._ask("second", "b") == "b"
    assert W._ask("third", "c") == "c"
    # Only the FIRST prompt reached input(); the latch served the rest.
    assert len(calls) == 1


def test_keyboard_interrupt_exits_cleanly(monkeypatch):
    def _interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)
    with pytest.raises(SystemExit) as excinfo:
        W._ask("Agent display name", "Jarvis")
    assert excinfo.value.code == 1


# ── explicit non-interactive contract ────────────────────────────────


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_noninteractive_env_takes_defaults_without_prompting(monkeypatch, value):
    monkeypatch.setenv(W._NONINTERACTIVE_ENV, value)

    def _boom(_prompt):  # pragma: no cover - must never run
        raise AssertionError("prompted while non-interactive")

    monkeypatch.setattr("builtins.input", _boom)
    assert W._ask("Agent display name", "Jarvis") == "Jarvis"
    assert W._ask_yn("Make default?", True) is True
    assert W._ask_choice("Pick", [("a", "A"), ("b", "B")], default=0) == "a"


def test_noninteractive_env_unset_still_prompts(monkeypatch):
    monkeypatch.setenv(W._NONINTERACTIVE_ENV, "0")
    monkeypatch.setattr("builtins.input", lambda _p: "Anakin")
    assert W._ask("Agent display name", "Jarvis") == "Anakin"


# ── custom GGUF path ─────────────────────────────────────────────────


class _Rec:
    def __init__(self, key):
        self.registry_key = key
        self.display_name = key
        self.size_gb = 1.0
        self.score_pct = 50.0
        self.tokens_per_task = 100
        self.notes = ""


def _pick_custom(monkeypatch, answers):
    """Drive _wizard_pick_model down the custom-path branch."""
    supplied = iter(answers)
    monkeypatch.setattr(W, "_ask_choice", lambda *a, **k: "__custom__")
    monkeypatch.setattr(W, "_ask", lambda *a, **k: next(supplied))
    return W._wizard_pick_model(
        role_label="Awake",
        rec_entry=_Rec("recommended-key"),
        discovered=[],
        by_key={},
        allow_same_as_awake=False,
        awake_choice=None,
    )


def test_custom_path_reprompts_on_empty_answer(monkeypatch, capsys):
    chosen = _pick_custom(monkeypatch, ["", "", "/models/real.gguf"])
    assert chosen == "/models/real.gguf"
    assert "enter a path" in capsys.readouterr().out


def test_custom_path_empty_never_returns_blank(monkeypatch):
    """A blank model would make Review print an empty 'Awake model'."""
    monkeypatch.setattr(W, "_no_answer_available", lambda: True)
    chosen = _pick_custom(monkeypatch, [""])
    assert chosen
    assert chosen == "recommended-key"


def test_custom_path_announces_recommended_fallback(monkeypatch, capsys):
    monkeypatch.setattr(W, "_no_answer_available", lambda: True)
    _pick_custom(monkeypatch, [""])
    out = capsys.readouterr().out
    assert "no path given" in out and "recommended-key" in out


# ── "same as awake" gate ─────────────────────────────────────────────


def test_asleep_gate_reads_operator_pick_not_tier_recommendation():
    """Pin the real call site in run_wizard.

    The bug was ``allow_same_as_awake=(rec.awake.registry_key
    != rec.asleep.registry_key)`` — keyed on the tier default, so the
    option vanished on every tier where the two recommendations coincide
    (<=8GB and >=64GB) even after the operator picked a different awake
    model. Assert on the source so a revert is caught here rather than by
    an operator mid-setup.
    """
    import inspect

    src = inspect.getsource(W.run_wizard)
    assert "allow_same_as_awake=(model_path != rec.asleep.registry_key)" in src
    assert "allow_same_as_awake=(rec.awake.registry_key" not in src


def test_same_as_awake_offered_when_pick_differs_from_asleep_rec():
    opts = _asleep_options(model_path="/custom/mine.gguf",
                           asleep_rec_key="gemma-4-26b-a4b-it-qat-q4_0")
    assert "__same_as_awake__" in opts


def test_same_as_awake_hidden_when_pick_equals_asleep_rec():
    opts = _asleep_options(model_path="gemma-4-26b-a4b-it-qat-q4_0",
                           asleep_rec_key="gemma-4-26b-a4b-it-qat-q4_0")
    assert "__same_as_awake__" not in opts


def _asleep_options(*, model_path, asleep_rec_key):
    """Option values _wizard_pick_model offers for the asleep slot."""
    import contextlib
    import io as _io
    import unittest.mock as mock

    captured: dict[str, list[str]] = {}

    def _capture(_prompt, options, default=0):
        captured["values"] = [value for value, _label in options]
        return options[default][0]

    with contextlib.redirect_stdout(_io.StringIO()):
        with mock.patch.object(W, "_ask_choice", _capture):
            W._wizard_pick_model(
                role_label="Asleep",
                rec_entry=_Rec(asleep_rec_key),
                discovered=[],
                by_key={},
                # Mirrors run_wizard's call site, pinned by the test above.
                allow_same_as_awake=(model_path != asleep_rec_key),
                awake_choice=model_path,
            )
    return captured["values"]
