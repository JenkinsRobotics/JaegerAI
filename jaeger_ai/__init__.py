"""JaegerAI — a general-purpose AI assistant platform.

JaegerAI combines models, tools, skills, memory, automation, delegation,
permissions, and native desktop, web, terminal, voice, and headless interfaces.
Local execution, personality, and physical-device capabilities are supported
deployment choices rather than limits on the product's scope. Named assistants
are configured instances of the platform, not forks of it.
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

__version__ = "0.11.0"
