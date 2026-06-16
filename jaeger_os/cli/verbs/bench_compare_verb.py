"""``jaeger bench compare`` — multi-model bench with an interactive picker.

The agent can't switch its own model mid-run, so multi-model comparison
is operator-driven by design. This verb is the friendly UX layer over
``benchmark/run_model_sweep.py`` — it discovers ``.gguf`` files on disk,
shows them in a numbered list, and lets the operator pick which ones
to bench. The sweep script does the rest (config swap, subprocess per
model, comparison report).

Flow:

  1. Scan known model dirs (``~/.lmstudio/models/`` by default plus
     any ``model.extra_gguf_dirs`` from the current config) for
     ``*.gguf`` files. Filter out mmproj sidecars.
  2. Print a numbered list with size + currently-active marker.
  3. Accept ``N,M,P`` / ``all`` / ``current`` from stdin. ``--models``
     bypasses the picker for scripts.
  4. Write the selection to a temp file and exec
     ``python benchmark/run_model_sweep.py /tmp/sel.txt``.
  5. The sweep writes its comparison markdown under
     ``benchmark/sweep/RESULTS_<ts>.md`` — we print the path so the
     operator knows where to read.

Args (all optional):

  --models PATH1,PATH2[,...]   Skip the picker; use these models.
  --tags ROUTING,MEMORY        Tag filter for the inner bench.
  --limit N                    Cap cases per model (after tag filter).
  --extra-dirs DIR1,DIR2       Additional directories to scan.
  --dry-run                    Show the selection but don't run.

Exit codes:
  0 — sweep completed (regardless of pass-rate; check the report).
  1 — no models discovered, or sweep failed to launch.
  2 — bad arguments / user cancelled.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Iterable


_DEFAULT_MODEL_DIRS: tuple[str, ...] = (
    "~/.lmstudio/models",
)


def _cmd_bench_compare_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger bench compare", add_help=False,
    )
    parser.add_argument(
        "--models", default=None,
        help="comma-separated model paths (skip picker)",
    )
    parser.add_argument(
        "--tags", default=None,
        help="bench tag filter (e.g. 'routing,memory'). Empty = full corpus.",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="cap cases per model after tag filter (0 = no cap)",
    )
    parser.add_argument(
        "--extra-dirs", default=None,
        help="comma-separated extra directories to scan for .gguf files",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="show the selection but don't actually run the sweep",
    )
    parser.add_argument(
        "--instance", default=None,
        help="instance name (default: active)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="bypass the memory-safety guard (DANGEROUS — large dense "
             "models can kernel-panic an Apple Silicon machine by "
             "exhausting unified memory). Only use if you know the "
             "model fits.",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        _print_help()
        return 0

    # Either --models given (scripted) or run the picker.
    if args.models:
        selected = _resolve_paths(args.models.split(","))
        if not selected:
            print("[jaeger bench compare] none of the --models paths "
                  "exist on disk", file=sys.stderr)
            return 2
    else:
        discovered = _discover_models(
            extra_dirs=(args.extra_dirs or "").split(","),
            instance_name=args.instance,
        )
        if not discovered:
            print("[jaeger bench compare] no .gguf models found under "
                  f"{', '.join(_DEFAULT_MODEL_DIRS)} — pass --extra-dirs "
                  "or use --models with explicit paths", file=sys.stderr)
            return 1
        current_path = _current_model_path(instance_name=args.instance)
        selected = _interactive_pick(discovered, current=current_path)
        if not selected:
            print("[jaeger bench compare] cancelled — no models selected",
                  file=sys.stderr)
            return 2

    # ── memory-safety guard ──────────────────────────────────
    # A bench must NEVER be able to kernel-panic the machine. Large
    # DENSE models on Apple Silicon's unified memory exhaust RAM,
    # thrash swap, and starve the kernel watchdog → panic + reboot.
    # (Confirmed twice on a 32 GB M1 Max: gemma-4-31B dense + Qwen3.6-27B
    # dense.) MoE models of the same on-disk size are safe because
    # only the active experts (~3-4B) drive sustained compute.
    safe, blocked = _memory_safety_partition(selected)
    if blocked and not args.force:
        print()
        print("⚠ MEMORY-SAFETY GUARD — the following model(s) are likely "
              "to crash this machine and were EXCLUDED:")
        for b in blocked:
            print(f"  ✗ {pathlib.Path(b['path']).name}  "
                  f"({b['size_gb']:.1f} GB, {b['kind']}) — {b['reason']}")
        print()
        if not safe:
            print("[jaeger bench compare] every selected model was blocked "
                  "by the memory-safety guard. Pick smaller / MoE models, "
                  "or pass --force if you're certain they fit.",
                  file=sys.stderr)
            return 2
        print(f"Proceeding with the {len(safe)} safe model(s) only. "
              f"Pass --force to include the blocked ones anyway.")
        selected = [s["path"] for s in safe]
    elif blocked and args.force:
        print()
        print("⚠ --force: running BLOCKED models despite the memory-safety "
              "guard. If the machine hangs, the kernel watchdog will "
              "reboot it. You were warned.")
        for b in blocked:
            print(f"  ! {pathlib.Path(b['path']).name} ({b['size_gb']:.1f} GB)")

    # Summary of the chosen set before launching.
    print()
    print(f"Selected {len(selected)} model(s) to benchmark:")
    for p in selected:
        size = _human_size(p)
        print(f"  - {pathlib.Path(p).name}  ({size})")
    print()
    if args.tags:
        print(f"Tags filter:   {args.tags}")
    if args.limit:
        print(f"Limit / model: {args.limit}")

    if args.dry_run:
        print("\n--dry-run: not launching sweep.")
        return 0

    # Write a temp file the sweep script can consume.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as fh:
        for p in selected:
            fh.write(p + "\n")
        models_file = fh.name

    repo = _repo_root()
    sweep_script = repo / "dev_benchmark" / "run_model_sweep.py"
    if not sweep_script.is_file():
        print(f"[jaeger bench compare] sweep script missing at {sweep_script}",
              file=sys.stderr)
        return 1

    print(f"\nLaunching sweep. This will run the bench once per model "
          f"(cold-load each time) — expect several minutes per model.\n")

    env = os.environ.copy()
    # Pass tag + limit through env so the sweep script can forward to
    # the inner ``run_flat_bench.py`` invocation. (The sweep accepts
    # these as env vars rather than CLI flags so the script's surface
    # stays stable for existing users.)
    if args.tags:
        env["JAEGER_BENCH_TAGS"] = args.tags
    if args.limit:
        env["JAEGER_BENCH_LIMIT"] = str(args.limit)
    # macOS fork-safety. The sweep driver imports numpy + jaeger
    # modules then fork()s each per-model bench subprocess. On
    # macOS 26's new "xzone" allocator, fork() after complex
    # allocation crashes the child in ``_malloc_fork_child``
    # (libmalloc assertion). ``MallocNanoZone=0`` selects the older
    # allocator that survives fork; ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY``
    # quiets the Metal/Obj-C fork guard. Both must be in the env at
    # process START, so we set them on the env the sweep inherits —
    # they propagate to its bench subprocesses too.
    env.setdefault("MallocNanoZone", "0")
    env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

    rc = subprocess.call(
        [sys.executable, str(sweep_script), models_file],
        env=env,
    )

    # Sweep writes its own report path; the script prints it. Surface
    # the SWEEP_DIR for the operator if the rc was ok.
    sweep_dir = repo / "dev_benchmark" / "sweep"
    if rc == 0:
        print(f"\nSweep complete. Reports under: {sweep_dir}")
    else:
        print(f"\n[jaeger bench compare] sweep exited rc={rc}",
              file=sys.stderr)
    return rc


# ── model discovery ─────────────────────────────────────────────


def _discover_models(
    *,
    extra_dirs: Iterable[str],
    instance_name: str | None,
) -> list[str]:
    """Walk known directories for ``.gguf`` files, filtering out
    mmproj sidecar files (they're not chat models). Sorted by path
    for stable picker numbering."""
    dirs: list[pathlib.Path] = []
    for d in _DEFAULT_MODEL_DIRS:
        dirs.append(pathlib.Path(d).expanduser())
    for d in extra_dirs:
        d = (d or "").strip()
        if d:
            dirs.append(pathlib.Path(d).expanduser())
    # Pull extra dirs from the instance config too.
    cfg_dirs = _config_extra_gguf_dirs(instance_name=instance_name)
    for d in cfg_dirs:
        dirs.append(pathlib.Path(d).expanduser())

    found: set[str] = set()
    for root in dirs:
        if not root.exists():
            continue
        for p in root.rglob("*.gguf"):
            name = p.name.lower()
            # Skip mmproj sidecars + projection files — not chat models.
            if "mmproj" in name or "projector" in name:
                continue
            found.add(str(p))
    return sorted(found)


def _config_extra_gguf_dirs(*, instance_name: str | None) -> list[str]:
    """Read ``model.extra_gguf_dirs`` from the active instance's
    config.yaml. Returns [] when no instance is bound or the field
    is missing."""
    try:
        from jaeger_os.core.instance.instance import (
            InstanceLayout, default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.core.instance.schemas import Config, load_yaml
    except Exception:  # noqa: BLE001
        return []
    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(root=resolve_instance_dir(name))
        if not layout.config_path.exists():
            return []
        cfg = load_yaml(layout.config_path, Config)
        extras = getattr(cfg.model, "extra_gguf_dirs", None) or []
        return [str(d) for d in extras]
    except Exception:  # noqa: BLE001
        return []


def _current_model_path(*, instance_name: str | None) -> str | None:
    """Return the currently-configured ``model.model_path`` so the
    picker can mark it. None when no instance / no config."""
    try:
        from jaeger_os.core.instance.instance import (
            InstanceLayout, default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.core.instance.schemas import Config, load_yaml
    except Exception:  # noqa: BLE001
        return None
    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(root=resolve_instance_dir(name))
        if not layout.config_path.exists():
            return None
        cfg = load_yaml(layout.config_path, Config)
        return getattr(cfg.model, "model_path", None)
    except Exception:  # noqa: BLE001
        return None


# ── picker ──────────────────────────────────────────────────────


def _interactive_pick(
    models: list[str],
    *,
    current: str | None,
) -> list[str]:
    """Numbered-list picker. Returns the user's selection (possibly
    empty if they cancelled with Ctrl-C or blank input).

    Accepts:
      - ``all``          → every model
      - ``current``      → just the currently-configured model
      - ``1,3,5``        → comma-separated indices (1-based)
      - blank / Ctrl-C   → cancel
    """
    print("Available models:")
    print()
    for i, p in enumerate(models, start=1):
        marker = "*" if current and p == current else " "
        name = pathlib.Path(p).name
        size = _human_size(p)
        print(f"  {marker} [{i:>2}] {name:<48} ({size})")
    if current and current not in models:
        print(f"\n  * = currently active (not discovered; passed via config)")
    elif current:
        print(f"\n  * = currently active")
    print()
    print("Pick models — comma-separated indices, 'all', 'current', "
          "or blank to cancel:")
    try:
        raw = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return []
    if not raw:
        return []
    if raw == "all":
        return list(models)
    if raw == "current":
        return [current] if current else []
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
        except ValueError:
            print(f"  (skipping non-numeric input: {part!r})", file=sys.stderr)
            continue
        if 1 <= idx <= len(models):
            selected.append(models[idx - 1])
        else:
            print(f"  (skipping out-of-range index: {idx})", file=sys.stderr)
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in selected:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ── memory-safety guard ──────────────────────────────────────────
#
# A benchmark must never be able to crash the host. On Apple Silicon
# the GPU shares the CPU's unified memory, so a model whose weights +
# KV cache + the OS working set exceed physical RAM forces heavy swap.
# Sustained swap thrashing under a DENSE model (every token touches
# every weight) starves the kernel watchdog → panic + reboot.
# Confirmed twice on a 32 GB M1 Max with gemma-4-31B (dense 18.7 GB)
# and Qwen3.6-27B (dense 16.5 GB).
#
# MoE models of the same on-disk size are safe: their weights are all
# resident, but only the active experts (~3-4B) drive compute each
# token, so sustained GPU/memory-bandwidth pressure is far lower and
# the machine stays responsive enough for the watchdog to check in.
#
# Heuristic:
#   * Detect MoE from the filename's active-param marker (``A3B`` /
#     ``A4B`` / ``-MoE``).
#   * DENSE models: block when weights exceed ``_DENSE_MAX_FRACTION``
#     of total RAM (default 0.45 — leaves headroom for KV + OS + the
#     sustained-compute working set).
#   * MoE models: block only when weights exceed ``_MOE_MAX_FRACTION``
#     (default 0.72 — they still have to FIT, but tolerate a larger
#     resident footprint because sustained pressure is lighter).

_DENSE_MAX_FRACTION = 0.45
_MOE_MAX_FRACTION = 0.72


def _total_ram_bytes() -> int:
    """Total physical RAM. macOS via ``hw.memsize``; Linux via
    ``/proc/meminfo``. Falls back to a conservative 16 GB when neither
    is available (so the guard errs toward caution)."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, timeout=3,
        ).strip()
        return int(out)
    except Exception:  # noqa: BLE001 — not macOS / sysctl missing
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb * 1024
    except Exception:  # noqa: BLE001
        pass
    return 16 * 1024 ** 3  # conservative fallback


def _is_moe(name: str) -> bool:
    """True when the filename signals a mixture-of-experts model via
    an active-param marker (``A3B``, ``A4B``) or an explicit ``MoE``
    tag. These tolerate larger resident footprints because only the
    active experts drive sustained compute."""
    import re
    low = name.lower()
    if "moe" in low:
        return True
    # ``A3B`` / ``A4B`` / ``A22B`` active-param marker.
    return bool(re.search(r"[-_.]a\d+b", low))


def _memory_safety_partition(
    paths: list[str],
    *,
    ram_bytes: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """Split ``paths`` into (safe, blocked) by the memory heuristic.

    Each list holds dicts ``{path, size_gb, kind, reason}`` so the
    caller can render an explanation. ``kind`` is "MoE" or "dense".
    A model whose size can't be read is treated as safe (we don't
    want a stat() failure to silently drop a model)."""
    ram = ram_bytes if ram_bytes is not None else _total_ram_bytes()
    ram_gb = ram / 1e9
    dense_cap = _DENSE_MAX_FRACTION * ram_gb
    moe_cap = _MOE_MAX_FRACTION * ram_gb

    safe: list[dict] = []
    blocked: list[dict] = []
    for p in paths:
        name = pathlib.Path(p).name
        try:
            size_gb = pathlib.Path(p).stat().st_size / 1e9
        except OSError:
            safe.append({"path": p, "size_gb": 0.0, "kind": "unknown",
                         "reason": "size unreadable; allowed"})
            continue
        moe = _is_moe(name)
        kind = "MoE" if moe else "dense"
        cap = moe_cap if moe else dense_cap
        if size_gb > cap:
            blocked.append({
                "path": p, "size_gb": size_gb, "kind": kind,
                "reason": (
                    f"{kind} weights {size_gb:.1f} GB exceed the "
                    f"{cap:.1f} GB safe cap for {ram_gb:.0f} GB RAM "
                    f"({'MoE' if moe else 'dense'} limit "
                    f"{int((_MOE_MAX_FRACTION if moe else _DENSE_MAX_FRACTION)*100)}%"
                    f" of RAM)"
                ),
            })
        else:
            safe.append({
                "path": p, "size_gb": size_gb, "kind": kind,
                "reason": "within safe cap",
            })
    return safe, blocked


# ── helpers ─────────────────────────────────────────────────────


def _resolve_paths(raw: Iterable[str]) -> list[str]:
    """Expand + validate paths passed via ``--models``."""
    out: list[str] = []
    for p in raw:
        p = (p or "").strip()
        if not p:
            continue
        expanded = pathlib.Path(p).expanduser().resolve()
        if expanded.exists():
            out.append(str(expanded))
        else:
            print(f"[jaeger bench compare] not found: {p}", file=sys.stderr)
    return out


def _human_size(path: str) -> str:
    try:
        bytes_ = pathlib.Path(path).stat().st_size
    except OSError:
        return "?"
    if bytes_ >= 1e9:
        return f"{bytes_ / 1e9:.1f} GB"
    if bytes_ >= 1e6:
        return f"{bytes_ / 1e6:.1f} MB"
    return f"{bytes_} B"


def _repo_root() -> pathlib.Path:
    # The verb runs from any cwd; find the repo by walking up from
    # this file's location. (``daemon/`` is two levels below the
    # top-level ``benchmark/`` directory in the source layout.)
    here = pathlib.Path(__file__).resolve()
    # Editable install: src/jaeger_os/daemon/bench_compare_verb.py
    # Site-packages: site-packages/jaeger_os/daemon/...
    # Walk up looking for ``benchmark/run_model_sweep.py``.
    for parent in [here, *here.parents]:
        candidate = parent / "dev_benchmark" / "run_model_sweep.py"
        if candidate.is_file():
            return parent
    # Fallback: the installed wheel doesn't ship benchmark/, the user
    # has to be on a checkout. Surface that explicitly when we try
    # to run the sweep.
    return here.parents[3]  # best guess; the rc=1 branch below catches it


def _print_help() -> None:
    print(
        "usage: jaeger bench compare [options]\n"
        "\n"
        "Interactive multi-model bench comparison. Discovers .gguf\n"
        "models on disk, shows a numbered picker, runs the full bench\n"
        "corpus against each selected model, writes a comparison\n"
        "report under benchmark/sweep/.\n"
        "\n"
        "options:\n"
        "  --models P1,P2[,...]     skip picker; use these paths\n"
        "  --tags ROUTING,MEMORY    bench tag filter\n"
        "  --limit N                cap cases per model (default: full corpus)\n"
        "  --extra-dirs D1,D2       extra dirs to scan for .gguf\n"
        "  --dry-run                show selection without launching\n"
        "  --instance NAME          instance to read config from\n"
        "\n"
        "Discovery default: scans ~/.lmstudio/models/. Add more dirs\n"
        "with --extra-dirs or by setting model.extra_gguf_dirs in\n"
        "config.yaml.",
        file=sys.stderr,
    )


__all__ = ["_cmd_bench_compare_argv"]
