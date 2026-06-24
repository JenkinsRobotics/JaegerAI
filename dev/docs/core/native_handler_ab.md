# Native chat-handler prototype — A/B benchmark

Branch: `prototype/native-chat-handler`. Run: 2026-05-20, single A/B
pass, M1 Max, `gemma-4-26B-A4B-it-Q4_K_M`.

## What was tested

Every llama-cpp turn used to feed conversation history back as **Hermes
XML** (`<tool_call>{json}</tool_call>` in assistant content,
`<tool_response>…</tool_response>` in user messages). But the Gemma 4
GGUF ships its own native tool template — `<|tool_call>call:name{…}`,
`<|tool_response>response:…`, `<|"|>` string tokens. So Gemma was
reading its own past actions in a foreign dialect.

The **native** path (`_to_native_messages`) instead emits structured
`tool_calls` + `tool` messages and lets each GGUF's own chat template
render the history in the model's native dialect. Switched by
`JAEGER_NATIVE_TOOLS` so the two are one binary, one variable.

## Results

| Level | Metric | Legacy | Native | |
|---|---|---|---|---|
| L1 | routing | 32/33 (97%) | 32/33 (97%) | flat |
| L1 | answer-check | 14/15 | 14/15 | flat |
| L2 | tool-set | 10/12 (83%) | 10/12 (83%) | flat |
| L2 | ordered | 6/7 | 5/7 | −1 |
| L2 | answer-check | 9/11 | 10/11 | +1 |
| L2 | **wall time** | **385.9s** | **241.9s** | **−37%** |
| L3 | passing | 5/6 (83%) | 4/6 (67%) | −1 |
| L3 | turn-level | 14/15 | 12/15 | −2 |
| L4 | overall passing | 8/10 (80%) | 8/10 (80%) | flat |
| L4 | no-hallucination | 9/10 | 10/10 | +1 |
| L4 | recovered | 1/1 | 0/1 | −1 |
| — | total wall | 1072.1s | 1120.3s | +5% |

## Case-level deltas

- **L2** — native lost `write-and-run-fib` (full fail) but fixed
  `write-syntax-error-fix-loop` (full pass). One hard write+run case
  swapped for another.
- **L3** — native lost `three-fact-build-up`: the "Also remember X"
  follow-up turns did not route to `remember`. (Same case flip-flopped
  across prior Lilith runs — a known noisy scenario.)
- **L4** — native's `run-python-syntax-error` and `write-and-fix-loop`
  produced empty answers, both tied to the pre-existing
  `ctx=16384` overflow (`ValueError: Requested tokens exceed context
  window`), not the handler.

## Verdict — a wash at n=1

The native path is the architecturally correct design — verified to
render Gemma's own dialect — but it produced **no measurable accuracy
win**. Every accuracy delta (L2 ordered −1, L2 answer +1, L3 −1, L4
no-halluc +1, L4 recovered −1) is a *single case*, and the Level 1-4
suite has documented run-to-run variance larger than that at one
sample. The only signal that stands out is **L2 wall time, 37% faster** —
worth confirming.

Conclusion: Gemma 4 is robust enough to a foreign-dialect history that
fixing it didn't move the benchmark. The hypothesis ("we're forcing a
format the model fights") is *true as a fact* but *not the lever* for
L2/L3 accuracy.

## Disposition

- `JAEGER_NATIVE_TOOLS` defaults **OFF** — legacy stays the proven
  baseline. Native is opt-in (`=1`) pending evidence.
- **Kept unconditionally** (not flagged — pure bug fixes):
  - `_parse_gemma_args` — recursive Gemma brace-arg parser, replacing
    the regex `_parse_loose_args` that silently dropped every unquoted
    key after the first quoted one.
  - `_extract_qwen_tool_calls` — Qwen3-Coder's `<function=…>` dialect,
    which the old parser could not read at all.
- **Before merging native-as-default**: run the A/B 3-5× per side to
  separate the L2 speedup (and any L3 effect) from noise.
