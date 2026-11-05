# human_needs

Pure, local-snapshot human-needs rules (the approved human-needs directive, J-077) and the message delivery policy.

- `policy.py`: `evaluate` and `decide_delivery` over `Signals` / `Message` / `DeliveryState`. No source or delivery adapters live here; callers pass a snapshot and act on the decision.

**Reconciled rule (agreed 2026-11-05, single source of truth — also stated in docs/PRODUCT.md):** human needs produce gentle nudges only, with quiet hours (22:00–07:00); they NEVER pause or outrank tasks, and Jaeger never contacts anyone else about them. Connection/purpose items are delivered only as a daily digest. Safety alerts are the exception: they repeat at most every 5 minutes and are never silenced by quiet hours.

Touchpoints: notification and check-in delivery decisions.
