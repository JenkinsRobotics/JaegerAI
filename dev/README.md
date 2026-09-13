# Development workspace

Application code lives in [jaeger_ai/](../jaeger_ai/). This directory contains
development tools, tests, research, and verification evidence.

| Directory | Purpose |
|---|---|
| [tests/](tests/) | Automated pytest suite; run `.venv/bin/python -m pytest -q` from the repository root |
| [scripts/](scripts/) | Developer setup, test drivers, generators, and packaging audits |
| [benchmark/](benchmark/) | Reproducible benchmarks and retained comparison results |
| [verification/](verification/) | Verification helpers, including the CPU-only import guard |
| [pipelines/](pipelines/) | Executable, manually run pipeline probes |
| [docs/](docs/) | Engineering documentation, plans, history, and release reports |
| [infographic/](infographic/) | Pipeline diagrams |
| [reference_ui/](reference_ui/) | Visual design references, not runtime assets |
| [tools/](tools/) | Specialized development tools |

[docs/pipelines/](docs/pipelines/) describes pipelines; [pipelines/](pipelines/)
contains executable probes. These are different roles, not duplicate trees.
`voice_sequential_halfduplex.py` is retained application-side voice R&D.

Release reviews belong under [docs/releases/0.12.0/](docs/releases/0.12.0/),
with raw measurements under `benchmark/results/`. Preserve baseline results
and historical reports; age alone does not make them disposable.

The root [scripts/install.sh](../scripts/install.sh) is a public installation
URL, whereas `dev/scripts/` is internal tooling. Root [docs/](../docs/) hosts
the public site. Neither should be merged into this development docs tree.
