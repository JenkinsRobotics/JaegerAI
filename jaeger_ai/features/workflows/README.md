# Workflows

Original, linear instruction definitions using the existing instance Library's managed documents, immutable revisions and recoverable archives. No second definition store or execution runtime. Definitions use `jaeger.workflow.v1`; unsupported executable/grant fields fail validation. Text/JSON imports are data; no URL fetch, module import, shell execution or permission installation occurs while editing/saving.

Run proposal captures the exact saved revision/digest and instructions in the existing durable Task owner. Existing originating conversation, caller, workspace, approval and tool policy remain authoritative. A proposal stays paused until approval; its receipt is not successful execution. Existing Tasks UI handles decisions/results. Stable control-operation receipts prevent blind repetition after uncertain writes. Removed definitions are archived/restorable; no permanent deletion.

Compatibility: existing `collections` gets the `workflows` classification; documents/versions/control operations/tasks remain existing owners/tables, no DB schema migration. Default Library document creation is unchanged. Rollback leaves workflow documents readable in Library and keeps unknown operation IDs and versioned device drafts. Full provider/browser/native acceptance remains separate from deterministic fixtures.
