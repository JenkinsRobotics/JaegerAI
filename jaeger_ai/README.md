# `jaeger_ai/` — Jaeger AI application package

Jaeger AI is the turnkey realtime agent application. It runs on JaegerOS and
embeds JaegerAgent as its mind; neither dependency is reimplemented here.

## Layout

`jaeger_os/` is the **framework** (read-only at runtime, upgraded in place by
`jaeger update`). Operator state lives entirely under the sibling
`.jaeger_ai/instances/<name>/` (each agent's identity, config, memory, skills,
workspace, logs, credentials) and is never touched by an upgrade. That
boundary is the safety contract: the agent can write its own skills + state,
never the framework code.

characters/      portable character/v1 packs and persona compilation
cli/             jaeger command dispatcher and verbs
core/            Jaeger AI application logic and runtime services
interfaces/      native Swift, PySide6, TUI, protocol, and avatar surfaces
modules/         provider-named adapters for imported Jaeger modules
nodes/           nodes owned by this application
plugins/         optional application extensions and messaging channels
skill_tree/      Jaeger AI skill progression and training state
timeline/        application timeline/event support
assets/          shared application assets
models/          model metadata and local model links
docs/            generated agent contract (release reports live in dev/docs)
```

The division follows the same application convention as Mochi:

- Code specific to Jaeger AI belongs in `core/`.
- A screen or client belongs in `interfaces/`.
- An app-owned runtime component belongs in `nodes/`.
- Integration with an imported provider belongs in `modules/<provider>.py`.
- A portable character is a folder directly under `characters/`.

Only entrypoint seams stay loose at package root. `main.py` is the application
entrypoint, while `module_roots.py` must remain importable at that location for
the `jaeger_os.module_roots` packaging entrypoint.

Operator state does not live in this package. It stays under
`.jaeger_os/instances/<name>/` (or the configured external instance root), so
upgrading Jaeger AI does not replace memory, credentials, logs, or workspaces.
