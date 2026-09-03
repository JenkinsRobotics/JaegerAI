"""Hardened subprocess transport shared by command-line delegate features."""

from .runtime import CommandSpec, SubprocessDelegateRuntime

__all__ = ["CommandSpec", "SubprocessDelegateRuntime"]
