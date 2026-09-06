# Ollama provider verification notes

Checked against official documentation on 2026-09-06. Research findings below
are not proof that every native adapter implements these capabilities yet.
No account, subscription, provider default, or installed runtime was changed.

## Current documented contract

- `glm-5.3-flash:cloud` remains the requested default. The model has always-on
  reasoning with low/high/max effort; an Off control must not imply reasoning
  is disabled. [Official model page](https://ollama.com/library/glm-5.3-flash)
- `glm-5.3:cloud` is the requested manual larger-model option. Its model page
  describes low/high/max reasoning effort.
  [Official model page](https://ollama.com/library/glm-5.3%3Acloud)
- Native `/api/chat` accepts a model-dependent `think` field. Thinking arrives
  separately from answer content. Effort choices must be validated per model,
  not copied from another provider's generic picker.
  [Thinking API](https://docs.ollama.com/capabilities/thinking)
- Terminal chat responses document `prompt_eval_count`,
  `prompt_eval_cached_count`, `eval_count`, and nanosecond duration fields.
  Preserve missing counts as unknown, not zero. Do not sum repeated cumulative
  totals from stream snapshots. Validate the OpenAI-compatible API separately.
  [Chat API](https://docs.ollama.com/api/chat)
- Published cloud rates per million tokens are:

  | Model | Input | Cached input | Output |
  | --- | ---: | ---: | ---: |
  | GLM-5.3 Flash | $0.15 | $0.03 | $0.50 |
  | GLM-5.3 | $1.40 | $0.26 | $4.40 |

  Current pricing describes monthly usage credits and token-based consumption.
  It also distinguishes new plans from legacy session/weekly limits: do not infer
  this account's active plan or change it. Concurrent requests can be queued;
  a queue delay is not evidence that an agent is offline.
  [Official pricing and usage FAQ](https://ollama.com/pricing)

## Remaining implementation and live gates

1. Verify installed Mac and Rack Ollama versions against the official release;
   use active-work-aware upgrade/rollback, never an unconditional restart.
2. Verify each host inventory independently and retain model tags/host identity
   through each native session override. No silent cross-host fallback.
3. Record per-inference native receipts with agent, native session/run/request,
   provider, selected host, returned model, counts, timestamps, and latencies.
4. Expose supported effort controls through native adapters, with a real request
   probe confirming the selected option reached the selected host/model.
5. Calculate only labelled cost estimates from dated rates and complete counts;
   unknown cache counts or account pricing must not become an exact invoice.
   Do not double-count thinking if it is already in provider output totals.
6. Keep provider totals separate from Roundtable totals and deduplicate replayed
   usage events. Verify UI display, persistence, retries and partial failures.

Existing source has host-specific discovery/routing and Jaeger model token
counters. Native session overrides and all-agent usage parity remain incomplete;
see `RELEASE_PROGRESS.md` for the release matrix.
