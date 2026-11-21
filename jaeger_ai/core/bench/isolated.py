"""Run agent-requested benchmarks outside the Gateway's live memory process.

The worker uses the same provider and JaegerAgent loop with disposable state.
It cannot restore/close the Gateway's SQLite stores or inherit its task owner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from dataclasses import asdict
from typing import Any


def run_isolated(client: Any, config: Any, **selection: Any):
    from jaeger_agent.tool_executor import active_caller_identity, active_tool_allowlist
    from jaeger_agent.util.tool_interrupt import run_interruptible
    from jaeger_ai.core.bench.runner import BenchRow
    from jaeger_ai.core.instance.instance import operator_state_root

    ext = getattr(client, "ext", None)
    if ext is None or ext.provider == "cli":
        raise ValueError("A Gateway benchmark requires an HTTP model provider (for example Ollama); "
                         "an in-process model or external agent CLI cannot be safely copied into the benchmark worker")
    parent = operator_state_root() / "bench-workers"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=parent) as temporary:
        root = Path(temporary)
        payload = {"config": config.model_dump(mode="json"), "external_model": ext.model_dump(mode="json"),
                   "caller": active_caller_identity(), "allowed_tools": sorted(active_tool_allowlist())
                   if active_tool_allowlist() is not None else None, "selection": selection}
        from jaeger_ai.main import _pipeline
        payload["system_prompt"] = _pipeline.get("system_prompt", "")
        request = root / "request.json"
        request.touch(mode=0o600)
        request.write_text(json.dumps(payload))
        env = dict(os.environ)
        env.update(JAEGER_STATE_DIR=str(root / "state"), JAEGER_HOME=str(root / "state"),
                   JAEGER_INSTANCE_DIR=str(root / "state/instances/benchmark"),
                   JAEGER_CALLER_TOKEN_DIR=str(root / "state/tokens"),
                   JAEGER_GATEWAY_URL="http://127.0.0.1:0", PYTHONDONTWRITEBYTECODE="1",
                   JAEGER_BENCH_WORKER_API_KEY=str(getattr(client, "_api_key", "") or ""))
        # One owned process group; cancellation/timeout uses the existing
        # tool-interrupt implementation and never signals unrelated workers.
        proc = run_interruptible([sys.executable, "-B", "-m", __name__, str(request)],
                                 timeout=900, cwd=str(root), env=env)
        response = root / "result.json"
        if proc.returncode or not response.is_file():
            from jaeger_ai.core.redaction import redact_text
            detail = redact_text(str(proc.stderr or ""))[-1500:]
            raise RuntimeError(f"Isolated benchmark worker failed (exit {proc.returncode}); "
                               f"no benchmark result was accepted. {detail}")
        result = json.loads(response.read_text())
        if result.get("error"):
            raise RuntimeError(result["error"])
        return [BenchRow(**row) for row in result["rows"]]


def _worker(request: Path) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, Identity, dump_yaml
    from jaeger_ai.core.models.external_model import ExternalModelClient
    from jaeger_ai.core.models.model_resolver import serving_model_scope
    from jaeger_agent.core.workspace import bind, project_scope
    from jaeger_agent.tool_executor import caller_identity, tool_allowlist
    from jaeger_os.core.safety.permissions import PermissionPolicy, DenyAllProvider, use_policy
    from jaeger_agent.tools.bench import _bench_permission_scope
    from jaeger_ai.core.bench.runner import run_bench
    from jaeger_ai.main import _pipeline

    payload = json.loads(request.read_text())
    layout = InstanceLayout(root=Path(os.environ["JAEGER_INSTANCE_DIR"]))
    layout.ensure_dirs()
    cfg = Config.model_validate(payload["config"])
    ext = ExternalModelConfig.model_validate(payload["external_model"])
    ext.api_key_credential = ""
    ext.api_key_env = "JAEGER_BENCH_WORKER_API_KEY"
    cfg.external_model = ext
    dump_yaml(layout.config_path, cfg)
    dump_yaml(layout.identity_path, Identity(name="Benchmark", role="Isolated benchmark",
                                            personality="Precise and evidence-driven"))
    bind(layout)
    client = ExternalModelClient(ext, layout)
    _pipeline.update(layout=layout, config=cfg, client=client,
                     system_prompt=payload.get("system_prompt") or "Complete the benchmark task using actual tools. Report failures truthfully.")
    # No external side effects can be approved by a detached worker. Local
    # benchmark writes retain the existing WRITE_LOCAL scope, confined to the
    # disposable instance by the ordinary tool workspace checks.
    with serving_model_scope(client, cfg), project_scope(layout.skills_dir), \
            caller_identity(payload.get("caller") or "benchmark"), \
            tool_allowlist(payload.get("allowed_tools")), \
            use_policy(PermissionPolicy(confirmation=DenyAllProvider())), _bench_permission_scope():
        rows = run_bench(client, hermetic=False, **payload["selection"])
    (request.parent / "result.json").write_text(json.dumps({"rows": [asdict(row) for row in rows]}))


if __name__ == "__main__":
    _worker(Path(sys.argv[1]))
