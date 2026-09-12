#!/usr/bin/env python3
"""Run the Chronicler trial with durable receipts; never score prose as memory."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import uuid

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = "http://127.0.0.1:8810"
DELAY_SECONDS = 7200


def save(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def decode_answer(text):
    clean = text.strip()
    if clean.startswith("```json") and clean.endswith("```"):
        clean = clean[7:-3].strip()
    value = json.loads(clean)
    if not isinstance(value, dict):
        raise ValueError("Response is not a JSON object")
    return value


def structure_checks(answer):
    """Mechanical checks only. Citation existence/support needs source review."""
    sources = answer.get("sources", [])
    claims = answer.get("claims", [])
    edges = answer.get("causal_edges", [])
    if not all(isinstance(v, list) and all(isinstance(x, dict) for x in v) for v in (sources, claims, edges)):
        return {"schema": False}
    source_ids = {s.get("id") for s in sources}
    claim_ids = {c.get("id") for c in claims}
    allowed = {"supported", "hypothesis", "disputed", "unknown"}
    adjacency = {c: [] for c in claim_ids}
    valid_edges = bool(edges) and all(e.get("from") in claim_ids and e.get("to") in claim_ids and e.get("status") in allowed for e in edges)
    if valid_edges:
        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting: return False
        if node in visited: return True
        visiting.add(node)
        if not all(visit(child) for child in adjacency[node]): return False
        visiting.remove(node)
        visited.add(node)
        return True
    regions = answer.get("regions", [])
    questions = answer.get("open_questions", [])
    word_count = len(str(answer.get("spoken_script", "")).split())
    return {
        "three_domains_declared": {"ice_core", "tree_ring", "historical"} <= {s.get("domain") for s in sources},
        "sources_have_locators": bool(sources) and all(s.get("url", "").startswith(("https://", "http://")) and s.get("locator") for s in sources),
        "claims_attributed": bool(claims) and all(c.get("status") in allowed and isinstance(c.get("source_ids"), list) and bool(c["source_ids"]) and set(c["source_ids"]) <= source_ids for c in claims),
        "causal_graph_is_dag": valid_edges and all(visit(n) for n in adjacency),
        "causal_edges_attributed": bool(edges) and all(isinstance(e.get("source_ids"), list) and bool(e["source_ids"]) and set(e["source_ids"]) <= source_ids for e in edges),
        "mermaid_provided": str(answer.get("mermaid", "")).strip().startswith(("graph", "flowchart")),
        "spoken_script_length": 125 <= word_count <= 165,
        "cadence_provided": bool(answer.get("cadence")),
        "three_regions": isinstance(regions, list) and {r.get("region") for r in regions if isinstance(r, dict)} == {"Byzantine", "Chinese", "Mesoamerican"},
        "two_distinct_questions": isinstance(questions, list) and len(questions) == 2 and all(isinstance(q, str) and q.strip() for q in questions) and questions[0] != questions[1],
    }


def read_memory(topic, memory_dir):
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.tools.insights import recall_insight, _honcho
    if not (memory_dir / "state.db").is_file():
        return {"status": "blocked", "error": "Native state.db not found"}
    sqlite_store.bind(SimpleNamespace(memory_dir=memory_dir))
    try:
        local = [recall_insight(topic, f"question-{i}") for i in (1, 2)]
        remote = (recall_insight(topic, "question-2", backend="honcho") if _honcho().health()
                  else {"ok": False, "found": False, "error": "Honcho unavailable"})
        return {"local": local, "honcho": remote}
    finally:
        sqlite_store.close()


def due_status(due_at, now):
    return "due" if now >= due_at else "pending"


def regional_table(answer):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| Region | Finding | Uncertainty | Sources |", "| --- | --- | --- | --- |"]
    for row in answer.get("regions", []):
        if isinstance(row, dict):
            lines.append("| " + " | ".join(cell(row.get(k, "")) for k in ("region", "finding", "uncertainty", "source_ids")) + " |")
    return "\n".join(lines) + "\n"


def source_snapshot():
    paths = subprocess.check_output(["git", "ls-files", "-m", "-o", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    return {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "working_files_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if (ROOT / p).is_file()}}


async def start(args, output):
    path = output / "report.json"
    if path.exists():
        raise ValueError("This run already exists. Inspect its request receipt; do not re-dispatch it.")
    run_id = uuid.uuid4().hex
    topic = "chronicle-" + run_id
    sid = topic
    contract = (ROOT / "docs/benchmarks/chronicler-trial.md").read_text()
    prompt = contract.split("<!-- BEGIN MISSION -->")[1].split("<!-- END MISSION -->")[0].strip()
    prompt += f"\nResearch topic for all records: {topic}\n"
    (output / "prompt.txt").write_text(prompt)
    trace = args.instance / "logs/trace.jsonl"
    offset = trace.stat().st_size if trace.exists() else 0
    report = {"run_id": run_id, "topic": topic, "session_id": sid, "request_id": run_id,
              "started_at": datetime.now(timezone.utc).isoformat(), "source": source_snapshot(),
              "scope": "single headless integration trial; not an intelligence benchmark",
              "research_quality": "unknown: independent source review required",
              "audio_generation": "not_tested: written script only",
              "agent_delayed_recall": "not_tested", "heartbeat": "not_tested",
              "overall_status": "incomplete", "trace_offset": offset}
    save(path, report)
    begun = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
            async def request(method, route, **kwargs):
                async with client.request(method, GATEWAY + route, **kwargs) as response:
                    body = await response.json()
                    if response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status}: {body}")
                    return body
            report["health"] = await request("GET", "/health")
            await request("POST", "/v1/sessions", json={"session_id": sid, "title": "Chronicler integration trial", "profile": "jaeger"})
            report["dispatch_attempted"] = True
            save(path, report)
            report["accepted"] = await request("POST", f"/v1/sessions/{sid}/turns", json={"text": prompt, "request_id": run_id})
            save(path, report)
            while time.monotonic() - begun < args.timeout:
                receipt = await request("GET", f"/v1/sessions/{sid}/requests/{run_id}")
                report["receipt"] = receipt
                save(path, report)
                if receipt["status"] in {"completed", "failed", "cancelled", "execution_unknown"}:
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError("Deadline reached; native execution may continue. Inspect receipt before retrying.")
            await finish_report(report, output, args)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["elapsed_s"] = time.monotonic() - begun
        if trace.exists():
            with trace.open("rb") as stream:
                stream.seek(offset)
                raw = stream.read()
            (output / "native-trace.jsonl").write_bytes(raw)
            report["trace_scope"] = "time window; may include other concurrent turns; not request-level attribution"
        save(path, report)
    print(json.dumps({"report": str(path), "native_completion": report.get("native_completion", False),
                      "error": report.get("error"), "delayed_storage": report.get("delayed_storage", "not_scheduled")}), flush=True)
    return 2  # Research review and the delayed check are still required.


async def finish_report(report, output, args):
    receipt = report.get("receipt", {})
    result = receipt.get("result", {})
    reconciliation = result.get("reconciliation") or result.get("native_receipt") or {}
    confirmed_native = (str(result.get("backend", "")).startswith("mcp") or
                        (reconciliation.get("execution_unknown") is False and
                         reconciliation.get("source") == "native_bridge_receipt"))
    report["native_reply_received"] = receipt.get("status") in {"completed", "failed", "cancelled"} and confirmed_native
    halt = (reconciliation.get("reply") or {}).get("halt_reason")
    report["native_completion"] = receipt.get("status") == "completed" and confirmed_native and not halt
    if halt:
        report["native_halt_reason"] = halt
    report["overall_status"] = "incomplete"
    answer_text = str(result.get("output") or (reconciliation.get("reply") or {}).get("text") or "")
    (output / "answer.txt").write_text(answer_text)
    if not report["native_reply_received"]:
        return
    answer = {}
    try:
        answer = decode_answer(answer_text)
        save(output / "answer.json", answer)
        report["structure_checks"] = structure_checks(answer)
        (output / "causal.mmd").write_text(str(answer.get("mermaid", "")))
        (output / "regional-table.md").write_text(regional_table(answer))
        (output / "spoken-script.txt").write_text(str(answer.get("cadence", "")) + "\n\n" + str(answer.get("spoken_script", "")))
    except (ValueError, TypeError, AttributeError) as exc:
        report["structure_error"] = str(exc)
    # Memory is inspected even when the output format failed.
    memory = await asyncio.to_thread(read_memory, report["topic"], args.instance / "memory")
    report["memory"] = memory
    questions = answer.get("open_questions", [])
    report["local_questions_match"] = len(questions) == 2 and len(memory.get("local", [])) == 2 and all(
        r.get("found") and (r.get("record") or {}).get("claim") == q for r, q in zip(memory.get("local", []), questions))
    second = (memory.get("local", [{}, {}])[-1].get("record") or {})
    if second.get("recorded_at"):
        report["delayed_storage_due_at"] = datetime.fromisoformat(second["recorded_at"]).timestamp() + DELAY_SECONDS
        report["delayed_storage"] = "pending"


async def collect(args, output):
    """Resume observation/reconciliation of the original ID, never execution."""
    path = output / "report.json"
    report = json.loads(path.read_text())
    sid, rid = report["session_id"], report["request_id"]
    began = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
            while time.monotonic() - began < args.timeout:
                async with client.get(GATEWAY + f"/v1/sessions/{sid}/requests/{rid}") as response:
                    response.raise_for_status()
                    receipt = await response.json()
                if receipt["status"] == "execution_unknown":
                    async with client.post(GATEWAY + f"/v1/sessions/{sid}/reconcile", json={"request_id": rid}) as response:
                        if response.status not in {200, 409}:
                            response.raise_for_status()
                        reconciled = await response.json()
                        report.setdefault("reconciliation_observations", []).append({
                            "at": time.time(), "http_status": response.status, "status": reconciled.get("status")})
                        if response.status == 200:
                            receipt = reconciled
                report["receipt"] = receipt
                save(path, report)
                if receipt["status"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(2)
            await finish_report(report, output, args)
    except Exception as exc:
        report["collection_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["collector_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        trace = args.instance / "logs/trace.jsonl"
        if trace.exists():
            since = datetime.fromisoformat(report["started_at"]).timestamp() * 1e9
            result = report.get("receipt", {}).get("result", {})
            attestation = result.get("reconciliation") or result.get("native_receipt") or {}
            until = float(attestation.get("observed_at") or time.time()) * 1e9
            lines = []
            for line in trace.read_text().splitlines():
                try:
                    if since <= json.loads(line).get("ts_ns", 0) <= until:
                        lines.append(line)
                except ValueError:
                    continue
            (output / "native-trace-final.jsonl").write_text("\n".join(lines) + "\n")
            report["trace_scope"] = "time window, not request-level attribution"
        save(path, report)
    print(json.dumps({"report": str(path), "native_completion": report.get("native_completion", False),
                      "overall_status": "incomplete", "collection_error": report.get("collection_error")}))
    return 2


def recall(args, output):
    path = output / "report.json"
    report = json.loads(path.read_text())
    due = report.get("delayed_storage_due_at")
    if not due:
        print("Blocked: no verified question-2 persistence timestamp.")
        return 2
    now = time.time()
    if due_status(due, now) == "pending":
        print(json.dumps({"status": "pending", "remaining_seconds": round(due - now)}))
        return 2
    memory = read_memory(report["topic"], args.instance / "memory")
    original = report["memory"]["local"][1]["record"]
    local = memory.get("local", [{}, {}])[-1]
    remote = memory.get("honcho", {})
    check = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "fresh-process storage retrieval, not agent recall",
             "local": bool(local.get("found") and local.get("record") == original),
             "honcho": bool(remote.get("found") and remote.get("record") == original), "readbacks": memory}
    save(output / "delayed-storage.json", check)
    report["delayed_storage"] = "passed" if check["local"] and check["honcho"] else "incomplete"
    save(path, report)
    print(json.dumps({k: v for k, v in check.items() if k != "readbacks"}))
    return 0 if report["delayed_storage"] == "passed" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "collect", "recall"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instance", type=Path, default=Path.home() / ".jaeger/instances/jaeger")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    args.instance = args.instance.expanduser().resolve()
    if output.is_relative_to(ROOT) or args.instance.is_relative_to(ROOT) or args.timeout <= 0:
        parser.error("state and output must be outside the repository; timeout must be positive")
    output.mkdir(parents=True, exist_ok=True)
    raise SystemExit(recall(args, output) if args.command == "recall" else
                     asyncio.run(start(args, output) if args.command == "start" else collect(args, output)))
