"""Small async helper so sync ARES tool wrappers can call the Monarch engine."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Run ``factory()`` on a dedicated event loop.

    ``factory`` must create the coroutine *inside* this helper so the coro is
    bound to the loop that executes it. Safe to call from sync MCP/ARES tools
    even if a loop is already running on the current thread.
    """

    def _call() -> T:
        return asyncio.run(factory())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _call()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_call).result()
