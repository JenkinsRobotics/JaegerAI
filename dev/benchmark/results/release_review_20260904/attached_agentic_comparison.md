# Multimodal agent comparison

Accuracy is the primary result. Latency is a tie-breaker only when the agents differ by at most one correct case.

| Metric | gemma-modular | jaeger-ai-attached-bridge |
|---|---:|---:|
| Correct | 19/19 | 19/19 |
| Task accuracy | 100.0% | 100.0% |
| Runtime errors | 0 | 0 |
| Spoken WER | 2.90% | 2.90% |
| Audio coverage | 100.0% | 36.8% |
| Model load | 15,698.95 ms | 108.81 ms |

## Per-case differences

- No correctness differences.
