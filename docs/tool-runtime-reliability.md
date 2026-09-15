# Tool runtime reliability

File searches include source files up to 16 MB. Results report skipped files,
traversal limits, and result limits explicitly. An incomplete search cannot prove
that a symbol has no callers. Credential exclusions still apply.

`read_file` returns at most 200 lines by default and 12,000 characters per page.
Use `next_offset` and `next_column` as the next call's `offset` and `column` to
resume, including within a long JSON line. Oversized file-read artifacts contain
the text itself, rather than another serialized file-read result.

Automatic skill selection uses the original request, before domain, world, and
ledger context are added. Continuations retain the original objective, do not
select another skill, and cannot create a work ledger named after a system nudge.
Existing permissions and execution limits remain enforced. Budget warnings ask
for an implementation/verification step or an incomplete checkpoint, not a
substitute report presented as completion.

Cloud/API adapters and their configured fallbacks honor
`external_model.max_tokens`. In-process adapters use `model.max_tokens`.
Reasoning uses the provider's output allowance too; exhaustion remains an
explicit incomplete result rather than an unbounded retry.

Regression coverage: `test_file_tools.py`, `test_autonomous_runner.py`,
`test_runtime_bridge.py`, and the agent package's context-guard/backstop tests.
