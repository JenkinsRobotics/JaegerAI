"""The ``jaeger`` framework's turn/reconciler pair resolves to live code, and
the retired REST adapter (RunsHTTP / frameworks.ingress) stays gone."""
from __future__ import annotations

import importlib

import pytest

from jaeger_ai.contract import frameworks as contract


def _resolve(ref: str):
    module, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module), attr)


def test_jaeger_turn_and_reconciler_resolve():
    spec_text = open(contract.__file__, encoding="utf-8").read()
    assert "jaeger_ai.core.frameworks.jaeger:dispatcher_turn" in spec_text
    assert "jaeger_ai.core.frameworks.jaeger:jaeger_reconcile" in spec_text
    assert callable(_resolve("jaeger_ai.core.frameworks.jaeger:dispatcher_turn"))
    assert callable(_resolve("jaeger_ai.core.frameworks.jaeger:jaeger_reconcile"))


def test_framework_module_exports_only_the_contract_pair():
    jaeger = importlib.import_module("jaeger_ai.core.frameworks.jaeger")
    assert sorted(jaeger.__all__) == ["dispatcher_turn", "jaeger_reconcile"]


def test_rest_adapter_is_retired():
    native_runs = importlib.import_module("jaeger_ai.core.frameworks.native_runs")
    assert not hasattr(native_runs, "RunsHTTP")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("jaeger_ai.core.frameworks.ingress")


def test_profile_key_is_stable_for_the_same_profile():
    from jaeger_ai.core.frameworks.native_runs import profile_key
    assert profile_key("default") == profile_key("default")
