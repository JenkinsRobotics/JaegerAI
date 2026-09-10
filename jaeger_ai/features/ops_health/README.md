# Ops health

Patterns for **honest** stack health — stolen in spirit from OpenClaw
daemon/healthcheck and Hermes crash-visibility ideas, implemented against
Jaeger’s bridge socket + adapter ports.

## Rule

`adapter_up ≠ bridge_up ≠ gateway_up`. A ready JSON from `:8642/health`
while `bridge.sock` refuses connections is a **split-brain** signal, not OK.

## This package

- `honesty.py` — `check_plane_health()` combines optional HTTP probes with
  `BridgeClient.health()` / socket connect.
- Docs only for launchd KeepAlive / recovery loops (see PORT.md) — no
  label renames in this pass.
