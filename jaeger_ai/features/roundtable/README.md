# 🏛️ Jaeger Roundtable Feature

> **Multi-Agent Collaboration & Consensus Orchestrator**  
> Enables **Jaeger**, **Hermes**, and **OpenClaw** to collaborate, debate, vote, and build consensus in a structured group environment.

---

## 📖 What is Roundtable?

Roundtable allows three distinct AI agents to participate in a shared discussion:
1. **🟩 Jaeger**: Local host operations, executive leadership, coding, and file operations.
2. **🟦 Hermes**: Deep reasoning, research, synthesis, and creative planning.
3. **🦞 OpenClaw**: Special tools, external API integrations, and audits.

Instead of one AI trying to do everything alone, Roundtable lets the three agents:
- Answer questions from different perspectives.
- Debate conflicting approaches.
- Vote and register formal decisions in an append-only ledger.
- Collaborate on multi-step tasks by assigning roles.

---

## 📂 Folder Contents & Architecture

Every file in this folder has a single, clear responsibility:

| File | What it does | When to edit it |
| :--- | :--- | :--- |
| **`roundtable.py`** | The HTTP server adapter and Server-Sent Events (SSE) streaming engine. | Edit when changing how messages stream to the Web UI or adding new API endpoints. |
| **`service.py`** | The `TableService` orchestrator that coordinates turns across the 3 agent sessions. | Edit when changing how agent sessions are instantiated or how turns execute. |
| **`policy.py`** | The debate rules, discussion modes, and consensus algorithms. | Edit when adjusting discussion modes (`ask`, `collaborate`, `vote`), turn limits, or rules. |
| **`progress.py`** | Tracks token budgets and emits real-time progress events. | Edit when changing timeout budgets or progress messages. |
| **`verify.py`** | Standalone verification test for Roundtable functionality. | Run directly to verify that all 3 agents can participate. |

---

## 🎯 Discussion Modes

You can configure how the agents interact via the `roundtable` parameter:

* **`ask`** *(default)*: Each agent provides an independent perspective, followed by a joint discussion and synthesis.
* **`collaborate`**: The agents divide a complex task into analysis, implementation, and review sub-tasks with assigned owners.
* **`vote`**: Agents submit structured proposals followed by recorded ballots.
* **`review`**: One agent drafts a proposal; the other two provide independent peer critiques.
* **`incident`**: Emergency mode separating diagnosis, evidence collection, and remediation proposals.

---

## 🚀 How to Test or Run Roundtable

### 1. Standalone Verification
To test that the agents can communicate and reach consensus:
```bash
python -m jaeger_ai.features.roundtable.verify
```

### 2. Automated Test Suite
Run the full pytest suite for Roundtable:
```bash
pytest dev/tests/jaeger_ai/interfaces/test_roundtable*.py
```

### 3. Through the Web UI
Open the Hermes Web UI (port 8642) and select the **Roundtable** profile from the profile selector!
