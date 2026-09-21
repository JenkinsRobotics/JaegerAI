# ARCHITECTURE_BEFORE.md — Jaeger Prior Architecture & Forensic Map

**Document Baseline:** JaegerAI master @ `f5e0b045` (Pre-Pinocchio Architecture)  
**Author:** Principal Systems Architect  
**Status:** Historical Reference  

---

## 1. Executive Summary: The Fragmented Center

Prior to the Pinocchio consolidation, Jaeger possessed extensive systems-engineering machinery (EffectLedger, checkpoints, SQLite persistence, tool repair, sandboxed subagents, audio nodes, native macOS clients), but lacked a single, unambiguous **persistent entity center**.

Instead of a single entity that remains continuous across models, sessions, and surfaces, the system was fragmented across multiple competing turn authorities, overlapping state stores, and conflated concepts.

```
                   JAEGER (BEFORE)
                         ?
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
       Gateway         Bridge       Heartbeat
      (:8810)       (AF_UNIX)      (Synthetic)
          │              │              │
          ↓              ↓              ↓
     _execute_turn    _run_turn    Fake User Chat
          │              │              │
          └──────────────┼──────────────┘
                         ↓
                    JaegerAgent
                         │
        ┌────────────────┼────────────────┐
        ↓                ↓                ↓
   belief_state.json  WorldModel      SQLite DBs
     (Disconnected)   (Isolated)     (Per-session)
```

---

## 2. Forensic Ownership Mapping

| Dimension | Previous Code Owner | Architectural Flaw / Failure Mode |
| :--- | :--- | :--- |
| **Identity vs Persona** | `jaeger_ai/core/instance/identity.py` | Conflated the agent's instance identity with a hardcoded character persona ("Lilith") and a specific operator ("Jonathan Jenkins"). Persona swap risked rewriting identity. |
| **Turn Authority** | Gateway `server.py`, Bridge `bridge.py`, MCP `mcp_server.py`, Autonomous Runner | 4 distinct execution paths. Gateway could fall back to bare Ollama text without native tools if native MCP dropped; Bridge ran local in-process loop; Heartbeat ran synthetic turns. |
| **Heartbeat Ingress** | `jaeger_ai/core/runtime/heartbeat.py` | Emitted synthetic *human* chat prompts (`"(Heartbeat) This is a standing check..."`), injecting fake conversational turns into session history. |
| **Beliefs vs World Model** | `jaeger_ai/features/reasoning/belief.py` vs `packages/jaeger-agent/.../world.py` | Competing versions of reality: `belief_state.json` (unstructured JSON cache) operated independently of `WorldModel` (SQLite entity/claim/relationship graph). |
| **Tool Consequence Observation** | `packages/jaeger-agent/.../tool_executor.py` | Tool results were consumed strictly within the active loop; not recorded as durable entity lifecycle events with execution consequences. |
| **Proactive Perception** | `jaeger_ai/features/reasoning/perception.py` | Confined to static machine telemetry (git dirty files, disk free GB, load avg). No concept of user activity / foreground application sensing. |
| **Skill Learning** | `packages/jaeger-agent/.../skill_registry/` | Extensive registry and benchmark code existed, but lacked an automated closed loop from execution attempt → verification test → library promotion. |
| **Between-Turn Cognition** | `jaeger_ai/features/reasoning/engine.py` | ARES reasoning ticks were isolated from episodic event transcripts; insights did not feed into the core world model. |

---

## 3. Structural Vulnerabilities in the Prior Design

1. **Model Conflation:** Model changes could cause conversational dislocation because session and persona prompts were tied to specific provider endpoints.
2. **Untruthful Event Provenance:** Fake human messages during heartbeats degraded transcript integrity and caused models to hallucinate human intent during automated checks.
3. **Competing State Authorities:** If `belief_state.json` diverged from SQLite knowledge tables, reasoning engines operated on stale or conflicting facts.
4. **Lack of Proactive Gating:** Without salience thresholding, background ticks either over-invoked expensive models or failed to act on environmental anomalies.
