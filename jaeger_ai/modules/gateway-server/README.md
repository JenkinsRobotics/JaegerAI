# gateway-server — monolith break-out module (split plan, NOT yet cut)

Original file: jaeger_ai/core/gateway/server.py, 388,486 bytes, the largest file in the repo. Gateway HTTP server on :33418, the control plane.

Why this folder exists: to make the split easy to edit, modify, and test, WITHOUT cutting server.py blind today. Cutting a 388KB control-plane file without a test run could break every client (IDE, WebUI, menubar shell, bridge) with no way to verify or fix it from here. This folder is the split map + test plan. The actual cut happens with code-run, one route group at a time, with Gateway tests passing after each group.

Already split around server.py (37 files in core/gateway/): caller_auth, handoff_controls, handoff_cancellation, handoff_stop_controls, handoff_ownership, handoff_reply, session_titler, session_hygiene, entity_memory, agent_memory, agent_templates, agent_summary, agent_presentation, skill_controls, connector_grants, upload_chunks, attachment_preview, attachment_access, pdf_preview, file_changes, turn_parts, global_stop, computer_status, diagnostic_capture, tool_inventory, policy_status, native_controls, native_mcp, openai_compat, connect_apps, event_bus, client, blueprint_routes, clean_slate.

Proposed split, leaving server.py as a thin router only:
- gateway-turns — turn admission, turn parts, turn finish, streaming.
- gateway-sessions — session create/list/archive, session titles/hygiene.
- gateway-handoffs — handoff create, controls, cancellation, stop, ownership, reply.
- gateway-approvals — approval requests, answers, policy status, global stop.
- gateway-uploads-attachments — upload chunks, attachment preview/access, pdf preview, file changes.
- gateway-admin-health — health, computer status, diagnostic capture, tool inventory, connector grants, native controls.

Rules for the cut: do NOT change any route URL, request/response shape, or approval semantics. Move code, keep imports working, run Gateway tests after each group. Do NOT split server.py, main-cli, and bridge in the same step — they are the three paths a turn travels.

Overlap with jaeger-agent: none for the Gateway server itself — jaeger-agent is the brain, the Gateway is JaegerAI's control plane. Do NOT copy jaeger-agent's agent loop into this module, and do NOT edit jaeger-agent to fit the Gateway.
