# human_needs

Pure, local-snapshot human-needs rules (the approved human-needs directive) and the message delivery policy.

- `policy.py`: `evaluate` and `decide_delivery` over `Signals` / `Message` / `DeliveryState`. No source or delivery adapters live here; callers pass a snapshot and act on the decision.

Touchpoints: notification and check-in delivery decisions.
