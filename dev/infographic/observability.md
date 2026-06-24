# Observability — pipeline trace → baseline

**Status: ✅ built** (this session).

```mermaid
flowchart LR
    turn["agent turn<br/>input · tool · think · answer"] -->|"/sense/trace_step (TraceStep)"| rec["TraceRecorder<br/>bus delivery thread"]
    rec --> jsonl["logs/trace.jsonl"]
    jsonl --> base["trace.baseline()<br/>avg/p50/p95 · per-tool freq+time"]
    panel(["future Studio<br/>Pipeline panel"]) -.->|"subscribe /sense/trace_step"| turn

    classDef built fill:#15402b,stroke:#3fae6f,color:#eafff2;
    classDef plan fill:#3a1530,stroke:#a64fa6,color:#ffe9fb,stroke-dasharray:5 3;
    class turn,rec,jsonl,base built;
    class panel plan;
```

**Flow.** Every turn emits one `TraceStep` per phase (`input → tool… → think → answer`) on `/sense/trace_step` **as it runs** — a queue `put_nowait`, so zero hot-path cost. A `TraceRecorder` (on the bus delivery thread, off the turn) appends each to `logs/trace.jsonl`. `python -m jaeger_os.agent.trace` prints the baseline (turn count, avg/p50/p95 total time, per-tool frequency + time); `--last` replays a turn's timeline. A future Studio "Pipeline" panel subscribes to the same topic for a live view.

**Key files:** `agent/trace.py` · `transport/topics.py` (`TraceStep`, `SENSE_TRACE_STEP`) · `main.py` (emit seams + recorder wiring). Rides on the existing per-tool `elapsed_s` + `LatencyReport` — no new timing code.
