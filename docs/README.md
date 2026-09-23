# JaegerAI documentation

Everything here is either enforced by a test or carries an obligation we
can't drop. Operator instructions live in the root [README](../README.md)
and [COMMANDS.md](../COMMANDS.md); contributor workflow lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

| Document | Purpose |
| --- | --- |
| [architecture/GROK_PERSONAL_RELEASE_PROMPT.md](architecture/GROK_PERSONAL_RELEASE_PROMPT.md) | Current five-day personal RC contract: Must gates, explicit holds, schedule and agent handoff; historical sections are labelled |
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | Topology and ownership, with each capability marked IMPLEMENTED / EXPERIMENTAL / PLANNED / DEPRECATED |
| [architecture/STATE_OWNERSHIP_MAP.md](architecture/STATE_OWNERSHIP_MAP.md) | Which component owns which fact. One fact, one owner |
| [architecture/TEST_ARCHITECTURE.md](architecture/TEST_ARCHITECTURE.md) | What each `run_tests.sh` tier actually proves |
| [architecture/THREAT_MODEL.md](architecture/THREAT_MODEL.md) | Trust domains, and what we explicitly do not defend against |
| [architecture/MASTER_PROGRAM_STATUS.md](architecture/MASTER_PROGRAM_STATUS.md) | Current release pointer and historical architecture program, not production certification |
| [architecture/DONOR_PROVENANCE.md](architecture/DONOR_PROVENANCE.md) | Attribution for ported code, with upstream commit SHAs and licenses |
| [architecture/adr/](architecture/adr/) | Why each architectural decision was made |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | Public capability, provider, and device contracts |

`index.html` is the source for the project website published on `gh-pages`.

Component docs stay with their code: [JaegerAgent](../packages/jaeger-agent/README.md),
[JaegerOS](../packages/jaeger-os/README.md),
[WebUI](../jaeger_ai/features/webui/README.md).

The master release contract is the single scope owner. Update it rather than
creating parallel roadmaps; dated audits and convergence logs are evidence, not
competing definitions of current release status.

Before adding a file here, check whether it belongs in a docstring, an ADR,
or a commit message instead. Status reports, dated audits, phase trackers,
and before/after snapshots do not belong in this directory — they go stale
in days and then actively mislead.
