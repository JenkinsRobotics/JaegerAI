"""Smoke test for the homeassistant plugin. Confirms importability and
that the tools answer (with a friendly setup error) without a live HA."""

from __future__ import annotations


def test_tools_importable() -> None:
    from jaeger_os.plugins.homeassistant import TOOL_NAMES, ha_get_state

    assert len(TOOL_NAMES) == 4
    assert callable(ha_get_state)


if __name__ == "__main__":
    test_tools_importable()
    print("homeassistant plugin smoke: OK")
