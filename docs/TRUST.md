# JaegerAI — on-device trust

Goal, not a current claim: your device becomes his device, and he owns it, so it must always be clear what stays on-device and what leaves it.

## Stays on device / NAS, always

- Memory, project graph, approvals, and audit log
- Raw audio and video, camera and microphone feeds
- Business files, CAD, G-code, and customer manufacturing data
- Robot and machine commands until they are approved and executed locally

## Leaves, named and logged only

- A cloud LLM call for a draft plan, summary, or explanation
- A web search for research
- A YouTube publish, or another external post the owner approved

Each leaving item is logged: what, why, for which job, and what was approved.

## Never leaves without a separate yes

- Robot / machine / drone commands
- Customer manufacturing data
- Training on customer data
- Silent telemetry — off by default, and named in the README if it is ever added

## Apple-first, staged

- Target Apple Silicon (Mac Studio, iPhone) with MLX / Core ML where a model actually exists, and plain Swift / Python tooling where it does not.
- Cloud LLM proposer now, MLX on-device later, same interface, only when a small model passes the same checks as the cloud model on the same tasks.
- No custom chip, custom OS, or custom inference engine in v1.
- Current state, honestly: Jaeger LLM work today uses cloud models. On-device is the direction to build toward, not something to claim today.
