---
name: dspy
description: "Build or optimize a DSPy language-model program. Use for explicit DSPy modules, signatures, teleprompters/optimizers, evaluated RAG pipelines, or migration from hand-written prompts to DSPy."
license: MIT
compatibility: Requires Python and DSPy plus a configured model provider.
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [execute_code, terminal]
    tags: [dspy, prompt-optimization, rag, evaluation]
    category: mlops
---

# DSPY PROGRAMS

## SOP

1. Define the task input/output contract and an evaluation metric first.
2. Check the DSPy version and configured provider without printing secrets.
3. Implement the smallest Signature and Module that express the task.
4. Create a representative train/dev set before selecting an optimizer.
5. Read `references/imported-guide.md` only for the chosen module, retrieval, or
   optimizer API; do not load the encyclopedia for a basic program.
6. Compare baseline and optimized metrics on held-out examples and save the
   optimized program plus reproducible configuration.

## ERROR HATCH

- No evaluation data/metric: stop at an unoptimized baseline and explain why.
- Provider/API mismatch: inspect the installed DSPy version rather than guessing
  constructor names from an older guide.

## DONE WHEN

The program runs reproducibly and the baseline-versus-optimized evaluation is
reported without test-set leakage.
