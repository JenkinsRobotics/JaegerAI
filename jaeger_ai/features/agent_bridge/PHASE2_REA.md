# REA status: unsupported, fail closed

No REA pass-through is enabled in this worktree. All 50 existing exact read-only
names below return 501 before goal admission. Unknown or mutating names return
403. A read-only label alone never authorizes a tool.

The cached REA 6.5.0 package uses an ambient active binary target. Some operations
accept an empty object; evidence can contain retained nested resource handles.
Its automatic provider selection and Hopper host leases do not establish private
caller/goal context. A second stdio process alone is insufficient isolation.
See [REA_FEASIBILITY.md](REA_FEASIBILITY.md) for inspected source contracts.

Enabling a subset requires a pinned private provider with no automatic installation
or network fallback, private state, enforceable workspace/resource confinement,
per-caller/goal opaque-handle ownership (including nested handles), and canonical
Jaeger permissions. No provider was launched or live registration changed here.

The isolated negative fixture proves a foreign file is never read through the
disabled REA surface. It does not qualify a private provider, balenaEtcher analysis,
or a real REA acceptance path. This remains an incomplete Part 1 requirement.

Exact unsupported tools:

- `open_binary`
- `binary_session`
- `binary_overview`
- `inspect_artifact`
- `inspect_binary_layout`
- `inspect_analysis_view`
- `analyze_javascript_application`
- `trace_application_feature`
- `trace_javascript_semantics`
- `compare_javascript_export_shapes`
- `trace_feature`
- `inspect_electron_fuses`
- `inspect_macho`
- `inspect_signature`
- `inspect_plist`
- `list_architectures`
- `demangle_swift`
- `decode_interface_builder`
- `inspect_keyed_archive`
- `inspect_asset_catalog`
- `trace_dylib_resolution`
- `list_strings`
- `search_strings`
- `list_procedures`
- `search_procedures`
- `list_segments`
- `list_names`
- `procedure_info`
- `procedure_assembly`
- `procedure_pseudo_code`
- `procedure_callers`
- `procedure_callees`
- `procedure_references`
- `xrefs`
- `get_call_graph`
- `analyze_function`
- `read_bytes`
- `search_bytes`
- `inspect_android_package`
- `inspect_pe_resources`
- `inspect_go_binary`
- `inspect_rust_binary`
- `inspect_sqlite_database`
- `project_apple_application_graph`
- `project_android_application_graph`
- `get_evidence_bundle`
- `list_unknowns`
- `evaluate_reconstruction_coverage`
- `verify_unknown_resolution`
- `compare_artifacts`
