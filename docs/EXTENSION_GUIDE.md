# Jaeger extension guide

Add capabilities, providers, tools, verifiers, and devices through **public
contracts**. Do not modify `EntityRuntime` for a new skill.

Status of this surface: **IMPLEMENTED** for validation CLI and manifests.
Installing a third-party capability into the live Gateway OWNER is
**EXPERIMENTAL**.

## Contracts

| Extension | Contract | Validate |
| :--- | :--- | :--- |
| Capability package | `jaeger_ai.core.capabilities.manifest.CapabilityManifest` | `jaeger capability validate <dir>` |
| Provider / model | `canonical_runtime_inventory()` + `CognitionProfile` | `jaeger provider doctor` |
| Device / node | `jaeger_ai.contract.schemas.Device` + `DeviceRegistry` | `jaeger device inspect` |
| Tool | `jaeger_agent` `ToolDef` + Authority tier | existing tool tests |
| Verifier | Effect verification pipeline | `dev/scripts/run_tests.sh --production-path` |
| Client | Gateway REST/SSE or AF_UNIX bridge | WebUI/CLI as ATTACHED_CLIENT |

## Capability package layout

```text
my-capability/
  manifest.yaml
  executor.py          # run(arguments, context=None)
  verifier.py          # optional verify(result, context=None)
  rollback.py          # optional revert(result, context=None)
```

`manifest.yaml` must include `capability_id`, `name`, `version`, and an
`execution_entrypoint` of the form `file.py:function` when `is_executable`
is true.

```bash
jaeger capability validate ./my-capability
```

Procedural skills (`is_executable: false`) are playbooks, not code the
runtime should import.

## Provider honesty

`jaeger provider doctor` prints the **canonical runtime inventory** used by
WebUI `/api/models`. Providers that exist only in code appear as
`SUPPORTED — NOT LIVE TESTED`. Missing credentials are not a command failure.

## Device honesty

Mac, Web, and phone are **clients**. `DeviceRegistry` is an experimental
in-memory contract for future sensors and robots. `jaeger device inspect`
says so.

## What you must not do

- Write Gateway SQLite from a client.
- Treat a unit test of your class as production verification.
- Promote agent-generated code into the kernel without the capability
  lifecycle (sandbox → tests → review).
- Claim a provider is available because the import exists.
