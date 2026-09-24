"""The isolation flag is defined once and defaults to the single Gateway path."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jaeger_ai.contract import legacy_paths
from jaeger_ai.contract.legacy_paths import (
    LEGACY_PATHS_ENV,
    disabled_reason,
    legacy_paths_enabled,
)

REPO = Path(__file__).resolve().parents[3]


def test_default_is_isolated():
    assert legacy_paths_enabled({}) is False
    assert legacy_paths_enabled({LEGACY_PATHS_ENV: ""}) is False
    assert legacy_paths_enabled({LEGACY_PATHS_ENV: "0"}) is False


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_explicit_opt_in_reenables(value):
    assert legacy_paths_enabled({LEGACY_PATHS_ENV: value}) is True


def test_reason_names_the_path_and_the_switch():
    text = disabled_reason("The in-process WebUI agent")
    assert "The in-process WebUI agent" in text and LEGACY_PATHS_ENV in text


def test_env_name_is_defined_once():
    """No other module may spell the variable; they import the contract."""
    offenders = []
    for root in ("jaeger_ai", "packages", "scripts"):
        for path in (REPO / root).rglob("*.py"):
            if "vendor" in path.parts or path == Path(legacy_paths.__file__):
                continue
            try:
                if re.search(r"""["']JAEGER_LEGACY_PATHS["']""", path.read_text(errors="ignore")):
                    offenders.append(str(path.relative_to(REPO)))
            except OSError:
                pass
    assert offenders == []
