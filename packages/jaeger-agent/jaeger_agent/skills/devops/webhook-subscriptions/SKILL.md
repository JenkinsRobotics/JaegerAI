---
name: webhook-subscriptions
description: "Configure and operate webhook subscriptions that trigger agent runs. Use when an external service event should start a Jaeger workflow or an existing webhook delivery needs diagnosis."
metadata:
  jros:
    version: 2.0.0
    lifecycle: core
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [terminal, read_file]
    tags: [webhook, events, automation, subscriptions]
    category: devops
---

# WEBHOOK SUBSCRIPTIONS

## SOP

1. Resolve provider, event types, callback endpoint, authentication/signature
   scheme, retry policy, and desired Jaeger prompt/action.
2. Inspect existing subscription and receiver state before creating or replacing.
3. Keep secrets in the credential/config system, never in URLs or logs.
4. Show the external subscription mutation and obtain confirmation.
5. Read `references/legacy-guide.md` only for provider-specific payload/lifecycle
   details, then create the narrowest event subscription.
6. Send or observe one signed test delivery and verify deduplication and response.

## ERROR HATCH

Signature failure, repeated delivery, unknown public endpoint, or ambiguous event
scope: disable/stop the test and report diagnostics. Never accept unsigned events
as a fallback.

## DONE WHEN

One authenticated test event produces exactly one expected run and subscription
identity/status are recorded.
