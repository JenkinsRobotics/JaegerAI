# REA confinement follow-up: concrete installed API assessment

The previously delivered `agent-bridge-review.patch` and manifest are preserved
unchanged. This follow-up does **not** complete REA pass-through and does not
advertise any supported `rea_*` operations. All 50 exact names remain 501, and
unknown/mutating names remain denied. This is an explicit incomplete acceptance
item, not a request to expand permissions or change production configuration.

## What was inspected without launching REA

The existing Jaeger REA registration points to `npx -y rea-agents@6.5.0 mcp`.
Only the command/package identity was extracted from configuration; no tokens,
headers or environment values were printed. No configuration was changed.
The already-cached package was then inspected read-only at:

`/Users/matthewjenkins/.npm/_npx/ad9a3fdbcad992c6/node_modules/rea-agents/`

No npm command, installer, doctor, provider, MCP server, model or live gateway
was started by this inspection.

Concrete source evidence in that package:

| Source | Observed API limitation |
| --- | --- |
| `dist/mcp/main-kBXHZ8S5.js:14564` | `BinarySession` owns one private `#active` target and transition queue. |
| `dist/mcp/main-kBXHZ8S5.js:14653` | `open(path, options)` switches that active target after draining current calls. This is a target transition, not a caller/thread lease. |
| `dist/mcp/main-kBXHZ8S5.js:69343` | `main` creates one `BinarySession` and supplies it to the MCP transport. |
| `dist/contracts/enhancedInputs.js:37` | `binary_overview` accepts a strict empty object. It cannot be bound to a bridge-owned target ID by adding an argument. |
| `dist/contracts/native/nativeToolContracts.js:68–77` | `inspect_macho` takes only detail; `inspect_signature` and `list_architectures` take empty objects. They use the active target. `inspect_plist` alone accepts an optional explicit path among these operations. |
| `dist/mcp/NativeMacOSProvider-Bh79k8dI.js:4644` | `inspect_plist` resolves the explicit path or active artifact and invokes host `file`/`plutil`. The provider still has a bound target and produces analysis evidence/locations; filtering the input path is not a general context-isolation mechanism. |
| `dist/contracts/sessionToolContracts.js:73` | `get_evidence_bundle` returns retained records for the session, including nested references. A bridge-generated UUID does not change the upstream record owner. |
| `dist/mcp/main-kBXHZ8S5.js:1280–1325` | Hopper startup acquires host leases and can encounter competing sessions. A separate MCP process is not by itself proof of a separate provider context. |
| `dist/mcp/main-kBXHZ8S5.js:220–245` | Provider selection defaults to `auto`; environment controls Hopper/Ghidra/IDA configuration. No generic caller/thread/workspace-root policy is supplied by this MCP request API. |

File hashes for reproducibility:

- `main-kBXHZ8S5.js`: `12a70d8ab2a57de0cc71d794e38470031bfbdde855ba4a435e0ac0613f2fe82e`
- `nativeToolContracts.js`: `20ecf3d3d5863d54550ccf6241684e6e0db67adef21f445872a620062d7e72f3`

## Assessed implementation choices

A bridge-owned registry **can** validate canonical paths and issue unguessable
local references. It cannot make an upstream empty-object operation address the
registered file. Serializing `open_binary` followed by an operation only inside
the bridge also cannot exclude another client of the shared upstream session.
Checking `binary_session` before/after is observational: a target can change
between those observations and the operation. Retaining returned handles,
including nested evidence references, would attribute ambient shared records to
the caller without proof. Such a registry would be a misleading security claim.

A private REA process per caller/thread/workspace is the viable direction, but
requires a pinned **private provider context**, not merely another stdio pipe.
Reusing the current `auto`/Hopper launch configuration risks host leases and
provider state shared with unrelated work; this task expressly preserves those
processes and state. An app-level path registry also does not constrain an
external provider's filesystem access or derived artifact/resource resolution.

The concrete prerequisite is either:

1. REA exposes a context-bound API whose target and evidence/resource identities
   can be validated per request, including a trusted workspace-root restriction;
   **or**
2. A verified private, non-shared provider launch contract is supplied for the
   adapter: pinned local executable/package, explicit provider selection with no
   automatic installation/network fallback, private HOME/state/cache/output and
   provider endpoints, and enforceable filesystem/resource confinement. Only
   tools supported by that context should be enabled; all others remain denied.

The second approach can then be implemented in Jaeger code with a per-context
handle registry, process ownership/cleanup, and the existing canonical
AuthorityLayer/PermissionPolicy. It does not require changing the shared REA
registration. This patch has not established or tested that provider launch and
filesystem contract. Manufacturing one from mocked providers would not prove
it safe. A scoped `inspect_plist` or `demangle_swift` subset is a potential later
candidate, not a supported operation advertised by this patch.

No registry scaffolding or unconsumed launcher was added just to claim progress.
New tests enumerate all 50 names and ensure each fails before admission, and
reject foreign handles and nested resource/reference fields. These tests prove
fail-closed unsupported behavior, **not** working handle confinement or REA
acceptance. Full Part 1 remains incomplete. Part 3 and the ordinary goal lifecycle
retain their previously reviewed behavior.

## Follow-up validation

The focused command in REVIEW.md now passes **201 tests**, including all 50
exact allowlisted names and three nested foreign-handle/resource cases. These
additional cases assert that no canonical request is admitted and no delegate
runs. Lint, formatting and `git diff --check` pass. Latest logs use the
`/tmp/jaeger-agent-bridge-checks/confinement-` prefix (`focused.log`,
`verify.log`, `smoke.log`). The final delivery reports completed pipeline results.
The previous patch and manifest retain their original SHA-256; the updated
artifact uses a separate `agent-bridge-review-v2.patch` filename.
