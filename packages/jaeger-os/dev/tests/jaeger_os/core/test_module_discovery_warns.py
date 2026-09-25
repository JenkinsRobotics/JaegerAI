"""A broken module install must not fail silently.

Discovery is fail-soft on purpose: a package that isn't installed
contributes nothing, and one bad contributor must not take down discovery
for everyone else. But an *installed* contributor whose entry point
raises is a different case — that is a broken install, and before this it
was completely invisible: ``discover_modules()`` returned ``{}`` and the
only symptom was a ``KeyError`` at some unrelated call site.

Found the hard way while installing JaegerAnimation into a clean venv
(FN-5): a missing transitive dependency made the module vanish with no
message of any kind.
"""

import logging

import pytest

from jaeger_os.core import modules


class _FakeEntryPoint:
    def __init__(self, name: str, exc: Exception | None = None,
                 roots: tuple = ()) -> None:
        self.name = name
        self.value = f"{name}.module_roots:roots"
        self._exc = exc
        self._roots = roots

    def load(self):
        if self._exc is not None:
            raise self._exc
        return lambda: self._roots


def _patch_eps(monkeypatch, eps):
    monkeypatch.setattr(
        modules.importlib.metadata, "entry_points",
        lambda group=None: eps,
    )


def test_a_broken_contributor_is_reported(monkeypatch, caplog):
    """The whole point: an ImportError must reach the operator."""
    _patch_eps(monkeypatch, [
        _FakeEntryPoint("brokenmod", exc=ImportError("no module named 'pydantic'")),
    ])
    with caplog.at_level(logging.WARNING, logger=modules.__name__):
        roots = modules._external_module_roots()

    assert roots == ()
    assert caplog.records, "a broken contributor produced no log record"
    msg = caplog.text
    assert "brokenmod" in msg, "the message must name the contributor"
    assert "pydantic" in msg, "the message must carry the real cause"


def test_a_broken_contributor_does_not_stop_the_others(monkeypatch, tmp_path):
    """Fail-soft is still the contract — one bad install must not hide
    every other module on the system."""
    good = tmp_path / "goodroot"
    good.mkdir()
    _patch_eps(monkeypatch, [
        _FakeEntryPoint("brokenmod", exc=RuntimeError("boom")),
        _FakeEntryPoint("goodmod", roots=(good,)),
    ])
    roots = modules._external_module_roots()
    assert good in roots


def test_healthy_discovery_stays_quiet(monkeypatch, tmp_path, caplog):
    """No warning when nothing is wrong — a noisy boot trains operators
    to ignore warnings."""
    good = tmp_path / "goodroot"
    good.mkdir()
    _patch_eps(monkeypatch, [_FakeEntryPoint("goodmod", roots=(good,))])
    with caplog.at_level(logging.WARNING, logger=modules.__name__):
        modules._external_module_roots()
    assert not caplog.records


def test_a_broken_metadata_index_is_reported(monkeypatch, caplog):
    """The other fail-soft path: entry_points() itself blowing up."""
    def _boom(group=None):
        raise RuntimeError("corrupt metadata")

    monkeypatch.setattr(modules.importlib.metadata, "entry_points", _boom)
    with caplog.at_level(logging.WARNING, logger=modules.__name__):
        assert modules._external_module_roots() == ()
    assert caplog.records
    assert "corrupt metadata" in caplog.text
