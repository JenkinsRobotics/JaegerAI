"""Hardware packages — one directory per robot.

Each package holds ``topology.yaml`` (validated by
``jaeger_os.hardware.package.load_package``), ``adapters/`` for its
controllers, ``devices/`` command builders, ``capabilities.py`` arg
models + handlers, and ``boot.py`` exposing
``load(bus=None) -> PackageRuntime``. See
dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md §5 for the add-a-robot recipe.
"""
