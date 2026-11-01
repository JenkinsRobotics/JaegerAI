# muse_bridge

File bridge between Muse (a cloud agent that can only read/write `~/Documents/Jaeger-Handoffs/muse/`) and the Jaeger hub as caller `muse`.

- `bridge.py`: picks up `requests/*.md|*.json` and `## TASK` blocks in `outbox.md`, hands them off through the loopback hub, polls for results and writes `replies/<id>.md`.

Touchpoints: the `jaeger-muse-bridge` LaunchAgent, hub handoffs, Backlog.
