"""Embodiment stays off until the control-plane release gate is actually green.

Minecraft and other embodiment entry points call this before any action.
A passing unit test is not the release gate.
"""
from __future__ import annotations


class EmbodimentDisabled(RuntimeError):
    pass


def assert_embodiment_allowed() -> None:
    raise EmbodimentDisabled(
        "Embodiment is disabled. The control-plane release gate has not passed."
    )


def minecraft_action(name: str, **_details: object) -> None:
    assert_embodiment_allowed()
