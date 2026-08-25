---
name: evaluating-llms-harness
description: "Benchmark a language model with EleutherAI lm-evaluation-harness. Use for explicit MMLU, GSM8K, HumanEval-style, or multi-task model evaluations requiring reproducible metrics."
license: MIT
compatibility: Requires Python, lm-eval, model weights or an API endpoint, and benchmark-specific compute.
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos]
    requires-tools: [terminal, execute_code]
    tags: [llm-evaluation, benchmark, lm-eval, metrics]
    category: mlops
---

# LM EVALUATION HARNESS

## SOP

1. Record the model revision, backend, precision, prompt/chat template, tasks,
   few-shot count, seed, and device before running anything.
2. Verify installed `lm_eval` version and list requested tasks.
3. Run a bounded smoke evaluation before the full benchmark.
4. Read `references/imported-guide.md` only for the selected backend, task
   composition, batching, or result analysis.
5. Save raw JSON results and command/config alongside the summary.
6. Compare models only when evaluation settings are identical.

## ERROR HATCH

- Out of memory: lower batch size first; do not silently change precision,
  model, task, or sample count.
- Unknown task/API: inspect the installed version's help and task list.

## DONE WHEN

Raw results and reproducible configuration exist, smoke/full status is clear,
and reported comparisons use matching settings.
