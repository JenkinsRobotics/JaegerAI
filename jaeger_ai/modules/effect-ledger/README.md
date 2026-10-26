# effect-ledger

Job: an authoritative action happens at most once. Unknown is not a guess.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/cognition/effects.py (6,102 bytes, vs 5,230 in clean standalone). Do NOT edit packages/jaeger-agent to change this again.

Contents: effects.py — once() with done / fresh / pending outcomes, EffectIndeterminate, ChannelDeliveryUnknown (transport outcome unknown, receipt is evidence never settlement).

How it bolts on (not yet wired, not yet tested): ledger wrapper registered by the host; verified-messaging uses this ledger. Clean jaeger-agent's cognition/effects.py stays in packages/jaeger-agent.

Test to run when code-run is available: run an effect twice (second time returns stored result, callable not re-invoked), crash mid-effect then resume (must raise indeterminate, must not silently re-send or skip).
