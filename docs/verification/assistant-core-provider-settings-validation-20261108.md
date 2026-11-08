# Validate provider preference updates before writing

This separate increment follows unreadable-document preservation. It rejects
invalid types rather than coercing them into a different setting or replacing
malformed saved provider entries.

## Verified defects and repair

The enabled field previously used bool(value): the string "false" enabled the
provider. Stored target-provider arrays convertible through dict(...) were
silently accepted; null or malformed scalars could raise uncaught TypeError.

The producer now requires an actual boolean when enabled is present, and an
object for the existing target-provider row. Rejection happens before any write
and maps through the existing HTTP 400 handling with static error text. Original
bytes remain identical; invalid first saves create no provider directory.

Valid boolean updates, omitted enabled, empty updates, unknown unrelated fields
and providers, first-save behavior and existing models validation/deduplication
remain intact. No credential, permission, authentication or CSRF change occurs.
This is not a comprehensive validator for every persisted field.

## Evidence

Frozen candidate ddb00ed410ffbfbe55b60460c5d7269e1c7c089a, following 40e0a75.
Incremental patch SHA-256:
3bc6cd2cdb50b7eddf164a4a8f2703cdc77b1df109a08f9b701e0cece3dd2381.

- Fail-before: 15 failed, 15 existing/compatible checks passed.
- Expanded focused suite: 68 passed, including the three inspected synthetic
  owned-loopback bridge tests; hygiene: 9 passed.
- Independent focused review: 98 passed, 6 deselected (five VS Code cases plus
  the obsolete control asserting the previous coercion behavior). It includes
  33 additional controls; independent hygiene: 9 passed.
- Main's identical preservation/validation file: 30 passed in 1.00 second.
  Production and test bytes match the reviewed candidate. Critical lint and
  whitespace checks pass. Counts overlap; no fresh full aggregate is implied.

Focused reproduction uses the external venv with disposable HOME/state/cache:

```sh
python -m pytest -q \
  dev/tests/jaeger_ai/features/webui/test_cli_settings_preservation.py \
  dev/tests/jaeger_ai/features/webui/test_cli_providers.py \
  dev/tests/jaeger_ai/features/webui/test_cli_providers_async.py \
  dev/tests/jaeger_ai/core/test_settings_catalog.py \
  dev/tests/jaeger_ai/core/test_config_atomic_patch.py \
  --basetemp=/path/to/fresh-external-state
```

Synthetic provider detection and token fixtures are not real provider/account
acceptance. Full source/client qualification remains separate.

The historical independent counts above were recorded in reviewer command
outputs, not separate retained log files. Their control files are included.
The later transaction report includes a fresh exact-final independent rerun
with complete saved logs.

## Separate concurrent-save follow-up

Independent controls reproduce stale read-modify-write loss and shared temporary
file consumption. Neither is corrected by these type checks. A subsequent
revision-bound atomic transaction must preserve a winning writer or return an
explicit conflict, keep unique temporary files and report uncertain commit
outcomes honestly. No automatic retries or permission changes are implied.

Overall and every tab remain PARTIAL. No runtime mutation, remote write, merge
or deployment occurred. All prior patches and failed controls are preserved.
