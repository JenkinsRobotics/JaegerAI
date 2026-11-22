#!/usr/bin/env python3
"""Run one live Gateway turn and evaluate its durable receipt.

This is the non-interactive test/evaluate half of the repair loop.  It never
asks the model to audit itself.  Results live under the operator state root,
not the repository.  A caller must explicitly opt into approval decisions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jaeger_ai.contract.ports import GATEWAY_PORT
from jaeger_ai.core.gateway.caller_auth import client_headers

TERMINAL = {"completed", "failed", "cancelled", "execution_unknown"}


def _call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    headers = {**client_headers("cli"), "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} returned {exc.code}: {detail}") from exc


def _result_root() -> Path:
    state = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    return Path(state or Path.home() / ".jaeger") / "qualifications" / "live-turns"


def evaluate_receipt(
    receipt: dict, *, expect_status: str, expect_output: list[str],
    expect_tools: list[str] | None, max_model_calls: int | None,
    max_steps: int | None,
) -> tuple[dict, list[str]]:
    """Pure evaluator used by both the live runner and its unit tests."""
    result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
    timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
    tool_rows = timing.get("tool_calls") if isinstance(timing.get("tool_calls"), list) else []
    tools = [str(row.get("name")) for row in tool_rows if isinstance(row, dict) and row.get("name")]
    output = str(result.get("output") or result.get("partial_output") or "")
    failures: list[str] = []
    if receipt.get("status") != expect_status:
        failures.append(f"status {receipt.get('status')!r} != {expect_status!r}")
    for expected in expect_output:
        if expected not in output:
            failures.append(f"output missing {expected!r}")
    if expect_tools is not None and tools != expect_tools:
        failures.append(f"tools {tools!r} != {expect_tools!r}")
    model_calls = timing.get("model_call_count")
    if max_model_calls is not None and (not isinstance(model_calls, int) or model_calls > max_model_calls):
        failures.append(f"model_call_count {model_calls!r} exceeds {max_model_calls}")
    steps = timing.get("continuation_step_count")
    if max_steps is not None and (not isinstance(steps, int) or steps > max_steps):
        failures.append(f"continuation_step_count {steps!r} exceeds {max_steps}")
    return {
        "status": receipt.get("status"), "tools": tools, "output": output,
        "model_calls": model_calls, "continuation_steps": steps,
    }, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--base", default=f"http://127.0.0.1:{GATEWAY_PORT}")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--approve", choices=("none", "once", "session"), default="none")
    parser.add_argument("--expect-status", default="completed")
    parser.add_argument("--expect-output", action="append", default=[])
    parser.add_argument("--expect-tools", help="Comma-separated exact tool sequence")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args()

    request_id = f"qualification-{uuid.uuid4()}"
    admitted = _call(args.base, "POST", f"/v1/sessions/{args.session}/turns", {
        "text": args.prompt, "request_id": request_id, "source": "cli",
    })
    request_id = str(admitted["request_id"])
    decided: set[str] = set()
    deadline = time.monotonic() + args.timeout
    receipt: dict = {}
    while time.monotonic() < deadline:
        receipt = _call(args.base, "GET", f"/v1/requests/{request_id}")
        if receipt.get("status") in TERMINAL:
            break
        approvals = _call(
            args.base, "GET", f"/v1/approvals?session_id={args.session}",
        ).get("approvals") or []
        for approval in approvals:
            aid = str(approval.get("approval_id") or "")
            if not aid or aid in decided or approval.get("request_id") != request_id:
                continue
            if args.approve == "none":
                continue
            _call(args.base, "POST", f"/v1/approvals/{aid}", {
                "approved": True, "decision": args.approve,
            })
            decided.add(aid)
        time.sleep(0.25)
    else:
        raise RuntimeError(f"request {request_id} did not finish within {args.timeout}s")

    expected_tools = None if args.expect_tools is None else [
        item.strip() for item in args.expect_tools.split(",") if item.strip()
    ]
    observed, failures = evaluate_receipt(
        receipt, expect_status=args.expect_status, expect_output=args.expect_output,
        expect_tools=expected_tools, max_model_calls=args.max_model_calls,
        max_steps=args.max_steps,
    )

    report = {
        "ok": not failures,
        "request_id": request_id,
        "session_id": args.session,
        **observed,
        "approval_decisions": len(decided),
        "failures": failures,
        "receipt": receipt,
    }
    root = _result_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{request_id}.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({**report, "receipt": str(destination)}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
