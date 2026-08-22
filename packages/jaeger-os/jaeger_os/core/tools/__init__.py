"""The tool contract — ``ToolDef`` + the process-wide registry.

Moved out of ``agent/schemas`` in the 0.9 CI-dependency-rule pass
(dev/docs/vision/THREE_TIER_STRUCTURE.md, law 2): the registry is a
shared substrate multiple producers write into (built-in agent tools,
hardware capabilities via ``hardware/capabilities.py``, plugin
tools) — the agent is its primary *reader*, not its owner. Living in
``core`` lets ``hardware/`` register capabilities as tools without
importing ``agent/``, which is exactly the inversion the nervous-system
rule requires.
"""
