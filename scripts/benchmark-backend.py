#!/usr/bin/env python3
"""Small, headless live benchmark of Jaeger's existing gateway chat contract.

Creates clearly named probe sessions and retains their transcripts as evidence.
Measures completion and correctness for simple tasks, not general intelligence.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
import uuid

import aiohttp


async def run(args):
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "gateway": args.gateway, "scope": "headless native chat smoke benchmark",
              "trials": []}
    output = args.output.expanduser().resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Benchmark output must be outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(report, indent=2) + "\n")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout)) as client:
        async def request(method, path, **kwargs):
            async with client.request(method, args.gateway + path, **kwargs) as response:
                body = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"{method} {path}: {response.status}: {body}")
                return body
        report["health_before"] = await request("GET", "/health")
        save()
        run_id = uuid.uuid4().hex[:10]
        sid = "backend-benchmark-" + run_id
        await request("POST", "/v1/sessions", json={"session_id": sid,
            "title": "Backend benchmark " + run_id, "profile": "jaeger"})
        report["session_id"] = sid
        for i in range(args.count):
            expected = args.expected or f"BACKEND_OK_{run_id}_{i}"
            prompt = args.prompt or "Reply exactly " + expected
            started = time.perf_counter()
            trial = {"index": i, "expected": expected, "prompt": prompt, "events": []}
            try:
                async with asyncio.timeout(args.timeout):
                    accepted = await request("POST", f"/v1/sessions/{sid}/turns",
                        json={"text": prompt})
                    trial["acceptance_s"] = time.perf_counter() - started
                    trial["turn_id"] = accepted["turn_id"]
                    async with client.get(args.gateway + f"/v1/sessions/{sid}/stream") as response:
                        response.raise_for_status()
                        async for line in response.content:
                            if not line.startswith(b"data:"):
                                continue
                            event = json.loads(line[5:])
                            if event["data"].get("turn_id") != trial["turn_id"]:
                                continue
                            trial["events"].append(event)
                            if event["event"] in {"turn.finish", "turn.failed", "turn.unknown", "turn.cancelled"}:
                                trial["terminal"] = event["event"]
                                trial["result"] = event["data"]
                                break
                    trial["completion_s"] = time.perf_counter() - started
                    session = await request("GET", f"/v1/sessions/{sid}")
                    matching = [m for m in session["messages"]
                                if m["role"] == "assistant" and m["content"].strip() == expected]
                    result = trial.get("result", {})
                    trial["passed"] = (trial.get("terminal") == "turn.finish"
                        and result.get("output", "").strip() == expected
                        and str(result.get("backend", "")).startswith("mcp")
                        and len(matching) == 1)
                    trial["persisted_exact_replies"] = len(matching)
            except Exception as exc:
                trial.update(passed=False, error=f"{type(exc).__name__}: {exc}",
                             completion_s=time.perf_counter() - started)
            report["trials"].append(trial)
            save()
            print(json.dumps({k:v for k,v in trial.items() if k not in {"events", "result"}}), flush=True)
            if not trial["passed"]:
                break  # Do not retry a possibly accepted native execution.
        durations = [t["completion_s"] for t in report["trials"] if t["passed"]]
        report["summary"] = {"requested": args.count, "attempted": len(report["trials"]),
            "passed": len(durations), "median_completion_s": statistics.median(durations) if durations else None,
            "max_completion_s": max(durations) if durations else None}
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps(report["summary"]), flush=True)
        return len(durations) == args.count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8810")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--prompt", help="Optional single custom probe; requires --expected and --count 1")
    parser.add_argument("--expected")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1 or args.timeout <= 0:
        parser.error("count and timeout must be positive")
    if bool(args.prompt) != bool(args.expected) or (args.prompt and args.count != 1):
        parser.error("custom prompt requires expected output and count 1")
    raise SystemExit(0 if asyncio.run(run(args)) else 1)
