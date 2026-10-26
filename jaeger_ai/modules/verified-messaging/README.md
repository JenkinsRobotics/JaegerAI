# verified-messaging

Job: send a message on an external channel only with a verified receipt, and never settle or retry an unknown send.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/tools/messaging.py (7,664 bytes, vs 5,218 in clean standalone). Do NOT edit packages/jaeger-agent to change this again.

Contents: messaging.py — send_message with reply_to_message_id correlation to the current Gateway conversation, host receipt validator, ChannelDeliveryUnknown for unknown outcomes. Depends on effect-ledger/ for the delivery-unknown exception and once-only rule.

How it bolts on (not yet wired, not yet tested): register send_message and certify_admin via the tool registry; receipt validator supplied by the host product, not imported from jaeger-agent. Clean jaeger-agent's messaging.py stays in packages/jaeger-agent.

Test to run when code-run is available: send, send with a bad reply target (must refuse, not send), send with transport outcome unknown (must raise unknown, must not retry).
