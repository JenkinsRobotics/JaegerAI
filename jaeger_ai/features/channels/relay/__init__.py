"""Owner-only phone channels for Jaeger (Telegram bot + iMessage self-chat).

One small relay process (``python -m jaeger_ai.features.channels.relay``,
launchd label ``com.jenkinsrobotics.jaeger-channels``) owns the transports:

* inbound messages from the owner become normal turns in the owner's home
  chat (``agent-native:jaeger``) through the Gateway, so phone and desktop
  share one history, and the reply goes back on the same channel;
* outbound deliveries (scheduled-job results, approval requests, proactive
  notifications) are queued by any process into a spool directory
  (:mod:`.outbox`) and sent by the relay;
* approvals can be answered from the phone (``approve 3f2a`` / ``deny 3f2a``).

Security model (same shape as Hermes ``pairing.py`` / OpenClaw allow-from):
Telegram accepts exactly one paired private chat id; iMessage only reads and
writes the owner's own self-chat (his own handles) and never addresses any
other conversation. Unknown senders are ignored without a reply.
"""

from .config import load_config, save_config, state_dir  # noqa: F401
from .outbox import enqueue  # noqa: F401
