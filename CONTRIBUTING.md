# Contributing to JaegerAI

Jaeger is a persistent-agent platform. The LLM is a replaceable cognition
provider. Please read [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
before changing execution, authority, state, or clients.

Current continuation state: [`docs/CONTINUE_FROM_HERE.md`](docs/CONTINUE_FROM_HERE.md).

## Branch policy

- Work on `pinocchio` (or a topic branch based on it).
- Do not merge `pinocchio` into `master` unless the operator asks.
- Do not rewrite published git history.
- Do not write runtime state into the repository tree. State belongs in
  `~/.jaeger` or `$JAEGER_STATE_DIR`.

## Development environment

```bash
./install.sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
# venv: ~/.jaeger/venv
```

Tests must isolate state:

```bash
export JAEGER_STATE_DIR=/tmp/jaeger-dev-iso
export JAEGER_NO_ATTACH=1
```

## Tests

See [docs/architecture/TEST_ARCHITECTURE.md](docs/architecture/TEST_ARCHITECTURE.md).

```bash
dev/scripts/run_tests.sh                 # default unit + packages
dev/scripts/run_tests.sh --unit          # fast unit only
dev/scripts/run_tests.sh --production-path
dev/scripts/run_tests.sh --security
dev/scripts/run_tests.sh --acceptance    # live Gateway + WebUI
```

Mocks are for unit tests. They are not production proof for routing,
authority, effects, attachments, identity, or recovery.

## Architecture rules

```text
MODEL != AGENT
SESSION != AGENT
CLIENT != AGENT
PROPOSED ACTION != AUTHORIZED ACTION
TOOL SUCCESS != VERIFIED SUCCESS
ONE FACT = ONE AUTHORITATIVE OWNER
```

- Gateway is the control plane. EntityRuntime owns execution.
- WebUI must not open Gateway SQLite.
- `jaeger-agent` must not import `jaeger_ai` implementation internals.
- Fail closed on Authority, routing, persistence, approvals, and recovery.
- Do not silently `except Exception: pass` on those paths.

## Adding an extension

Use public contracts. Do not edit `EntityRuntime` to add a skill, provider,
or device adapter.

```bash
jaeger capability validate path/to/package
jaeger provider doctor
jaeger device inspect
```

Details: [docs/EXTENSION_GUIDE.md](docs/EXTENSION_GUIDE.md).

## Pull requests

- One coherent change per PR / commit series.
- Include tests at the tier the change actually affects.
- Update architecture status if you change IMPLEMENTED / EXPERIMENTAL behavior.
- Conventional prefixes used on this branch: `feat(upaa)`, `arch(...)`,
  `fix(upaa)`, `docs(...)`, `test(...)`, `security:`.

## Security

Report vulnerabilities privately. See [SECURITY.md](SECURITY.md).
