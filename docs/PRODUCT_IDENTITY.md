# JaegerAI product identity

JaegerAI is a general-purpose AI assistant platform. This is the primary
product category used in public documentation, package metadata, onboarding,
and model-facing prompts.

## Product promise

JaegerAI connects models, tools, skills, persistent memory, automation,
delegated workers, and user interfaces in one locally controlled assistant.
It can run on a personal computer, server, or device and can use local,
hosted, or installed CLI models.

The primary remote experience is Jaeger WebUI over Tailscale. The browser UI
and its runtime adapter stay bound to loopback; Tailscale publishes the UI to
the operator's private tailnet. Public chat networks and third-party messaging
accounts are not required to reach the assistant.

## Capabilities, not identities

The following are supported capabilities and deployment options. None should
be used as a synonym for the whole product:

- Voice and avatars are interfaces.
- Jaeger WebUI is the primary remote interface.
- Discord, Telegram, Slack, and similar channels are optional plugins, not
  core product surfaces or roadmap requirements.
- Personality and characters are optional interaction layers.
- JaegerAgent is the reusable agent engine.
- JaegerOS is the runtime and capability foundation.
- Robotics and physical hardware are deployment targets.
- “Mind,” “body,” and “embodiment” are architectural metaphors or historical
  terminology, not the public product category.

Documentation should lead with the general assistant use case and introduce
specialized capabilities afterward. Runtime prompts must describe only the
capabilities actually available in that session; they must not imply that an
assistant is a robot, has a body, uses voice, or belongs to one named operator
unless the instance configuration explicitly says so.

## Positioning rule

Prefer:

> A general-purpose AI assistant platform with local and hosted models,
> tools, skills, memory, automation, delegation, and native interfaces.

Avoid positioning JaegerAI primarily as a “robot brain,” “embodied agent,”
“the Mind,” or a character system. Those descriptions narrow the model's and
the reader's understanding of an otherwise general platform.

## Architecture vocabulary

Use concrete layer names in technical writing:

1. **JaegerOS** — runtime, capability bus, nodes, supervision, and safety.
2. **JaegerAgent** — model adapters, agent loop, tools, skills, context, and
   delegation.
3. **JaegerAI** — complete assistant product, policy, memory, automation,
   interfaces, and instance management.
4. **Optional modules and deployments** — speech engines, messaging adapters,
   desktop clients, servers, and hardware packages.

Historical documents may retain their original language when clearly marked
as historical. Current README files, website copy, schemas, help text, and
prompts follow this document.
