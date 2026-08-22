#!/usr/bin/env python3
"""Ollama Cloud Agentic Evaluation & Multi-Model Comparison Tool.

This tool automates discovery, evaluation, and comparative benchmarking of
models hosted on Ollama Cloud (https://ollama.com/v1) and compares their agentic
performance (tool-routing, trajectory fidelity, multi-turn state, latency, TTFT)
against local models.

Usage:
    # 1. Discover available cloud models and test connectivity
    python dev/benchmark/ollama_cloud_eval.py --list

    # 2. Run quick smoke evaluation on a single cloud model
    python dev/benchmark/ollama_cloud_eval.py --model qwen3.5:397b --quick

    # 3. Sweep multiple cloud models and compare
    python dev/benchmark/ollama_cloud_eval.py --sweep qwen3.5:397b,llama3.3:70b,deepseek-v4-flash:preview --quick

    # 4. Compare cloud models against a local baseline
    python dev/benchmark/ollama_cloud_eval.py --compare --models gemma-4-e4b-it-q4_k_m,ollama-cloud:qwen3.5:397b --quick
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from typing import Any


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").is_file():
            return p
    return here.parents[2]


_REPO = _repo_root()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
os.chdir(_REPO)

# Curated recommended agentic models on Ollama Cloud
RECOMMENDED_MODELS = [
    ("qwen3.5:397b", "High-capacity flagship model for complex tool use and reasoning"),
    ("llama3.3:70b", "Strong general-purpose 70B open-weights agent baseline"),
    ("deepseek-v4-flash:preview", "Ultra-fast low-latency MoE reasoning model"),
    ("deepseek-v4-pro:preview", "High-precision deep reasoning model"),
    ("mistral-large-3:675b", "Large-scale function-calling & complex instruction model"),
    ("gemma4:31b", "Compact MoE conversational agent model"),
    ("kimi-k2.7-code", "Specialized code execution and skill authoring model"),
]


def resolve_cloud_api_key() -> str:
    """Resolve the Ollama Cloud API key from env or active instance credentials."""
    for env_var in ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val

    # Check instance credentials
    try:
        from jaeger_ai.core.instance.instance import resolve_instance_dir
        instance_dir = resolve_instance_dir(None)
        cred_file = instance_dir / "credentials" / "ollama_cloud_api_key"
        if cred_file.is_file():
            txt = cred_file.read_text(encoding="utf-8").strip()
            if txt:
                return txt

        alt_file = instance_dir / "credentials" / "ollama_api_key"
        if alt_file.is_file():
            txt = alt_file.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception:
        pass

    return ""


def list_available_cloud_models(api_key: str | None = None) -> list[dict[str, Any]]:
    """Query Ollama Cloud for available models."""
    key = api_key or resolve_cloud_api_key()
    if not key:
        print("[!] No Ollama Cloud API key found in environment or credentials.", file=sys.stderr)
        print("    Set OLLAMA_API_KEY or save it with: jaeger credentials set ollama_cloud_api_key", file=sys.stderr)
        return []

    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "JaegerAI-Evaluator/0.10.0",
    }

    # Query /api/tags
    url = "https://ollama.com/api/tags"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", [])
    except Exception as exc:
        # Fallback to /v1/models
        v1_url = "https://ollama.com/v1/models"
        req_v1 = urllib.request.Request(v1_url, headers=headers)
        try:
            with urllib.request.urlopen(req_v1, timeout=10) as resp:
                v1_data = json.loads(resp.read().decode("utf-8"))
                return [{"name": m.get("id"), "details": {}} for m in v1_data.get("data", [])]
        except Exception as exc2:
            print(f"[!] Error fetching models from Ollama Cloud: {exc} (v1 fallback: {exc2})", file=sys.stderr)
            return []


def print_cloud_catalog(models: list[dict[str, Any]]) -> None:
    """Pretty-print the Ollama Cloud model catalogue."""
    print("=" * 80)
    print("  OLLAMA CLOUD MODEL CATALOG & AGENTIC CANDIDATES")
    print("  Endpoint: https://ollama.com/v1")
    print("=" * 80)

    model_names = {m.get("name") for m in models if m.get("name")}

    print("\n★ RECOMMENDED AGENTIC CANDIDATES:")
    for model_id, desc in RECOMMENDED_MODELS:
        status = "✓ Available" if model_id in model_names else "• Cloud Tag"
        print(f"  {status:14s}  \033[1;36m{model_id:26s}\033[0m  {desc}")

    if models:
        print(f"\nALL AVAILABLE MODELS ({len(models)}):")
        for m in sorted(models, key=lambda x: x.get("name", "")):
            name = m.get("name", "")
            size = m.get("size", 0)
            size_str = f"{size / (1024**3):.1f} GB" if size else "Hosted"
            modified = m.get("modified_at", "")[:10] if m.get("modified_at") else ""
            print(f"  • \033[1m{name:30s}\033[0m  {size_str:10s}  {modified}")
    print("=" * 80)


def run_benchmark_sweep(
    models: list[str],
    *,
    quick: bool = False,
    corpus: str = "A",
    category: str = "",
    limit: int = 0,
) -> int:
    """Run dev/benchmark/bench.py across the specified model targets."""
    formatted_models = []
    for m in models:
        m = m.strip()
        if not m:
            continue
        if ":" not in m and not m.endswith(".gguf") and not (m.startswith("gemma") or m.startswith("qwen")):
            # Default bare model names to ollama-cloud
            m = f"ollama-cloud:{m}"
        formatted_models.append(m)

    if not formatted_models:
        print("[!] No models specified for benchmark sweep.", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        str(_REPO / "dev/benchmark" / "bench.py"),
        "--models",
        ",".join(formatted_models),
    ]
    if quick:
        cmd.append("--quick")
    if corpus != "A":
        cmd.extend(["--corpus", corpus])
    if category:
        cmd.extend(["--category", category])
    if limit > 0:
        cmd.extend(["--limit", str(limit)])

    print(f"\n>>> Running Evaluation Sweep across {len(formatted_models)} model(s)...", flush=True)
    print(f"    Command: {' '.join(cmd)}\n", flush=True)

    return subprocess.run(cmd).returncode


def generate_comparison_matrix(results_dir: pathlib.Path) -> str:
    """Read recent run summaries and format a markdown comparative performance matrix."""
    runs: list[dict[str, Any]] = []
    if results_dir.exists():
        for model_dir in results_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for ts_dir in model_dir.iterdir():
                if not ts_dir.is_dir():
                    continue
                summary_file = next(ts_dir.glob("*-summary.json"), None)
                if summary_file and summary_file.is_file():
                    try:
                        data = json.loads(summary_file.read_text(encoding="utf-8"))
                        data["_dir_ts"] = ts_dir.name
                        runs.append(data)
                    except Exception:
                        pass

    if not runs:
        return "No evaluation runs found in results directory."

    # Sort runs by timestamp descending
    runs.sort(key=lambda r: r.get("run_id") or r.get("_dir_ts", ""), reverse=True)

    lines = [
        "# Agentic Multi-Model Performance Comparison",
        "",
        "| Model | Provider | Pass % | Passed / Total | Avg Latency | P50 / P95 Latency | TTFT | Tok/s | Routing Acc | Safety Gate |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in runs[:15]:
        name = r.get("model_name", "unknown")
        provider = r.get("provider", "local")
        passed = r.get("passed", 0)
        total = r.get("total", 1) or 1
        pct = (passed / total) * 100
        m = r.get("metrics") or {}
        avg_lat = f"{m.get('avg_latency_s', 0):.2f}s"
        p50 = f"{m.get('p50_latency_s', 0):.2f}s"
        p95 = f"{m.get('p95_latency_s', 0):.2f}s"
        ttft = f"{m.get('avg_ttft_s', 0):.2f}s" if m.get("avg_ttft_s") else "-"
        tps = f"{m.get('answer_tokens_per_sec', 0):.1f}" if m.get("answer_tokens_per_sec") else "-"

        breakdown = r.get("category_breakdown") or {}
        routing_info = breakdown.get("routing")
        routing_acc = f"{routing_info['passed']}/{routing_info['total']}" if routing_info else "-"

        safety_info = breakdown.get("safety")
        safety_acc = f"{safety_info['passed']}/{safety_info['total']}" if safety_info else "-"

        prov_tag = f"**{provider}**" if provider != "local" else "local"
        lines.append(
            f"| `{name}` | {prov_tag} | **{pct:.1f}%** | {passed}/{total} | {avg_lat} | {p50} / {p95} | {ttft} | {tps} | {routing_acc} | {safety_acc} |"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="List available models on Ollama Cloud and verify API connectivity.")
    parser.add_argument("--model", help="Run benchmark on a single Ollama Cloud model (e.g. qwen3.5:397b).")
    parser.add_argument("--sweep", help="Comma-separated cloud models to sweep (e.g. qwen3.5:397b,llama3.3:70b).")
    parser.add_argument("--compare", action="store_true", help="Print recent multi-model comparative performance matrix.")
    parser.add_argument("--models", help="Comma-separated list of any mixed local and cloud models to benchmark.")
    parser.add_argument("--quick", action="store_true", help="Run quick 8-case smoke suite.")
    parser.add_argument("--corpus", choices=["A", "B"], default="A", help="Which benchmark corpus (A=original, B=generalization).")
    parser.add_argument("--category", default="", help="Filter by category (routing, memory, code, safety, etc.).")
    parser.add_argument("--limit", type=int, default=0, help="Cap number of cases.")
    args = parser.parse_args()

    key = resolve_cloud_api_key()
    if args.list:
        models = list_available_cloud_models(key)
        print_cloud_catalog(models)
        return 0

    if args.compare and not (args.models or args.model or args.sweep):
        results_dir = _REPO / "dev/benchmark" / "results"
        print(generate_comparison_matrix(results_dir))
        return 0

    targets = []
    if args.model:
        targets.append(f"ollama-cloud:{args.model}")
    if args.sweep:
        for m in args.sweep.split(","):
            if m.strip():
                targets.append(f"ollama-cloud:{m.strip()}")
    if args.models:
        for m in args.models.split(","):
            if m.strip():
                targets.append(m.strip())

    if not targets:
        print("[!] No benchmark action specified. Running model discovery by default...")
        models = list_available_cloud_models(key)
        print_cloud_catalog(models)
        return 0

    rc = run_benchmark_sweep(
        targets,
        quick=args.quick,
        corpus=args.corpus,
        category=args.category,
        limit=args.limit,
    )

    print("\n" + "=" * 80)
    print(generate_comparison_matrix(_REPO / "dev/benchmark" / "results"))
    print("=" * 80)
    return rc


if __name__ == "__main__":
    sys.exit(main())
