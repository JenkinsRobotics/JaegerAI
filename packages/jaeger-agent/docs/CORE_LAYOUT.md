# JaegerAgent 1.2 core layout

JaegerAgent follows the same high-level anatomy as Jaeger Agent Omni:
implementation plumbing belongs to `core/`; capability extension surfaces stay
visible at package top level.

```text
jaeger_agent/
├── __init__.py   public Python API
├── __main__.py   single `python -m jaeger_agent` entry point
├── module.yaml   JaegerOS module manifest
├── core/         agent/runtime and multimodal implementation
├── nodes/        neural, audio, and vision capability nodes
├── tools/        symbolic actions
├── skills/       reusable procedures
├── memory/       persistent agent state
└── loop/         agent-loop components
```

The package root deliberately contains no implementation-module facades. Code
imports implementation details from `jaeger_agent.core`; consumers that only
need the stable API import its symbols directly from `jaeger_agent`.

## Core ownership

These modules have one home under `jaeger_agent/core/`:

- `availability`, `bridge`, `config`, `context`, `contracts`, `credentials`
- `engine`, `errors`, `events`, `host`, `instance`, `messages`
- `module_roots`, `node`, `policy`, `runner`, `runtime`, `safety`
- `selfcheck`, `trace`, `usage`, `workspace`

Mutable runtime settings also have one home. For example,
`jaeger_agent.core.context.STRUCTURED_CONTEXT` is the setting read by the
engine; there is no root-level copy that can drift from it.

## Entry points

- `python -m jaeger_agent`: run the multimodal face.
- `python -m jaeger_agent selfcheck [--json]`: run the model-free package
  health check.
- `jaeger_agent:make_mind_node`: construct the JaegerOS mind-slot node declared
  by `module.yaml`.
- `jaeger_agent.core.module_roots:roots`: expose packaged module roots through
  the console entry point in `pyproject.toml`.

## Layout guard

`tests/test_packaged_assets.py` asserts that the package root contains only
`__init__.py`, `__main__.py`, and `module.yaml`, that every core module exists,
and that node manifests, weights, stats, prompts, and skills ship with the
installed package.
