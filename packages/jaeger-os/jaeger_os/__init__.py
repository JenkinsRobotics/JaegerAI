"""JaegerOS — the framework layer of the Jaeger ecosystem.

Bus, Node, the module/slot system, the supervisor, the safety floor,
the wire contract, and the hardware capability layer. Libraries +
standards + tooling, the way ROS is to a robot stack — projects and
modules BUILD ON this, pinned to a release; nothing here imports the
Mind (see ``dev/tests/jaeger_os/core/test_layering.py``).

Everything you need to write an app is importable from HERE:

    from jaeger_os import JaegerApp, Bus, InProcBus, Node, topics

    bus = InProcBus()
    bus.subscribe(topics.ACT_DISPLAY_FRAME, on_frame)
    bus.publish(topics.DisplayCommand(asset_path="idle.gif"))

You never have to know that a Bus lives in ``transport`` or that Node
lives in ``nodes.base``. Those paths still work and are what the
framework uses internally — these are the SAME objects re-exported,
not a second API wrapping the first. There is one way to do everything;
this is just a shorter way to reach it.

Resolved lazily (PEP 562), for two reasons that both matter: importing
``jaeger_os`` must not drag in pyzmq, and the subpackages import each
other, so eager re-export here would be a circular import.
"""

__version__ = "0.10.0"

#: name -> (module, attribute). The whole public surface, in one place
#: an operator can read. Deliberately small: everything here is
#: something an app or a module actually needs, and anything that only
#: the framework uses stays behind its own subpackage.
_EXPORTS = {
    # Composing an app
    "JaegerApp": ("jaeger_os.app", "JaegerApp"),
    "load_manifest": ("jaeger_os.app", "load_manifest"),
    "load_config": ("jaeger_os.app", "load_config"),

    # Talking on the bus
    "Bus": ("jaeger_os.transport", "Bus"),
    "InProcBus": ("jaeger_os.transport", "InProcBus"),
    "topics": ("jaeger_os.contract", "topics"),

    # Writing a node
    "Node": ("jaeger_os.nodes.base", "Node"),
    "FrameNode": ("jaeger_os.nodes.base", "FrameNode"),
    "NodeState": ("jaeger_os.nodes.base", "NodeState"),

    # Modules and slots
    "discover_modules": ("jaeger_os.core.modules", "discover_modules"),
    "load_module": ("jaeger_os.core.modules", "load_module"),
    "ModuleSpec": ("jaeger_os.contract.modules", "ModuleSpec"),

    # Topic paths and delivery policy
    "topic_path": ("jaeger_os.contract.paths", "parse"),
    "for_instance": ("jaeger_os.contract.paths", "for_instance"),
    "qos_for": ("jaeger_os.contract.qos", "qos_for"),
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str):
    """Resolve a public name on first use (PEP 562)."""
    try:
        module_name, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module 'jaeger_os' has no attribute {name!r}. "
            f"Public names: {', '.join(sorted(_EXPORTS))}"
        ) from None
    import importlib

    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value          # cache; __getattr__ runs once
    return value


def __dir__():
    return sorted(__all__)
