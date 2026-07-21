"""JaegerAI — the turnkey agentic-AI product (the Mind) of the Jaeger ecosystem.

Agent loop, tools, skills, memory, the id/ego persona pipeline, local
inference, and its own faces (chat app, TUI, voice, protocol). Runs on
device by default, on top of a pinned JaegerOS (the framework tier).
Concrete agents (Lilith, ARES, …) are *instances* of this product, not
forks of it.
"""

# macOS fork-safety: Apple's Objective-C runtime aborts a forked
# child the first time it touches a class the parent initialized.
# Python's stdlib (ssl, locale, platform, …) drags Obj-C in before
# we get a chance to fork from the daemon path, so by the time
# ``jaeger start`` forks, llama-cpp-python's Metal backend dies
# silently inside ``ggml_metal_device_init`` in the child. The
# documented workaround is this env var; we set it at framework
# import time so it's in place BEFORE the parent's first
# transitive Obj-C touch. ``setdefault`` so an operator who has
# their own opinion on the policy can override us.
import os as _os
if _os.uname().sysname == "Darwin":
    _os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

__version__ = "0.9.6"
