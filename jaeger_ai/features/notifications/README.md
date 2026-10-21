# Notifications

In-app notification center over existing Gateway activity_history. Metadata-only titles; never message/tool bodies. Preferences and monotonic read watermark live in existing schema_meta under notifications:operator. Same one-local-operator boundary as agent presentation, not independent WebUI accounts. Existing authenticated read/admin routes; no OS authorization request, external push, new grants or transcript/approval mutation. Muting affects notifications only, not tasks, messages, approvals or execution.
