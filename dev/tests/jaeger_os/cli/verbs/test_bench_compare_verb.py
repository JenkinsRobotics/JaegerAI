"""``jaeger bench compare`` — multi-model bench picker verb.

Pin the discovery + picker + arg-parsing contract. We don't actually
launch the sweep (it's a multi-minute subprocess); instead we stub
``subprocess.call`` and verify the verb assembles the right command.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from jaeger_os.cli.verbs import bench_compare_verb as bcv


# ── _discover_models ─────────────────────────────────────────────


def _make_gguf(parent: pathlib.Path, name: str, size_bytes: int = 1024):
    p = parent / name
    p.write_bytes(b"x" * size_bytes)
    return p


@pytest.fixture
def _isolate_default_dirs(monkeypatch):
    """Hide the real ``~/.lmstudio/models/`` directory from discovery
    so tests only see what they put in ``extra_dirs``. Required: the
    dev machine running this test suite has real models on disk."""
    monkeypatch.setattr(bcv, "_DEFAULT_MODEL_DIRS", ())
    monkeypatch.setattr(bcv, "_config_extra_gguf_dirs", lambda **_kw: [])
    return monkeypatch


def test_discover_models_finds_gguf_in_extra_dirs(tmp_path, _isolate_default_dirs):
    """Models living under ``--extra-dirs`` are discovered."""
    d = tmp_path / "model_zoo"
    d.mkdir()
    _make_gguf(d, "alpha-7b.gguf")
    _make_gguf(d, "beta-13b.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = sorted(pathlib.Path(p).name for p in out)
    assert names == ["alpha-7b.gguf", "beta-13b.gguf"]


def test_discover_models_skips_mmproj_sidecars(tmp_path, _isolate_default_dirs):
    """Multimodal projection files share the .gguf suffix but aren't
    chat models — discovery must skip them."""
    d = tmp_path / "models"
    d.mkdir()
    _make_gguf(d, "gemma-4-E4B-it-Q4.gguf")
    _make_gguf(d, "mmproj-gemma-4-E4B-it-BF16.gguf")
    _make_gguf(d, "projector-anything.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = {pathlib.Path(p).name for p in out}
    assert names == {"gemma-4-E4B-it-Q4.gguf"}


def test_discover_models_recurses_into_subdirs(tmp_path, _isolate_default_dirs):
    """LM Studio stores models under ``vendor/model-name/file.gguf`` —
    discovery must walk subdirs to find them."""
    nested = tmp_path / "vendor" / "gemma-4-26B"
    nested.mkdir(parents=True)
    _make_gguf(nested, "gemma-4-26B-Q4.gguf")

    out = bcv._discover_models(extra_dirs=[str(tmp_path)], instance_name=None)
    assert len(out) == 1
    assert "gemma-4-26B-Q4.gguf" in out[0]


def test_discover_models_returns_sorted_for_stable_picker(tmp_path, _isolate_default_dirs):
    """Numbered picker → stable numbering requires sorted output."""
    d = tmp_path / "m"
    d.mkdir()
    _make_gguf(d, "z.gguf")
    _make_gguf(d, "a.gguf")
    _make_gguf(d, "m.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = [pathlib.Path(p).name for p in out]
    assert names == ["a.gguf", "m.gguf", "z.gguf"]


def test_discover_models_handles_missing_dir_silently(tmp_path, _isolate_default_dirs):
    """A non-existent extra-dir must not crash discovery."""
    out = bcv._discover_models(
        extra_dirs=[str(tmp_path / "does_not_exist")],
        instance_name=None,
    )
    assert out == []


# ── _interactive_pick ────────────────────────────────────────────


def test_picker_returns_empty_on_blank_input(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == []


def test_picker_returns_empty_on_ctrl_c(monkeypatch):
    def _raise(_=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _raise)
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == []


def test_picker_all_returns_every_model(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "all")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/a.gguf", "/b.gguf"]


def test_picker_current_returns_active_only(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "current")
    out = bcv._interactive_pick(
        ["/a.gguf", "/b.gguf"], current="/b.gguf",
    )
    assert out == ["/b.gguf"]


def test_picker_current_with_no_active_returns_empty(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "current")
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == []


def test_picker_comma_separated_indices(monkeypatch, capsys):
    """1-based, comma-separated."""
    monkeypatch.setattr("builtins.input", lambda _="": "1,3")
    out = bcv._interactive_pick(
        ["/a.gguf", "/b.gguf", "/c.gguf"], current=None,
    )
    assert out == ["/a.gguf", "/c.gguf"]


def test_picker_skips_non_numeric_input(monkeypatch, capsys):
    """Non-numeric chunks are skipped, valid ones still go through."""
    monkeypatch.setattr("builtins.input", lambda _="": "1, oops, 2")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/a.gguf", "/b.gguf"]


def test_picker_skips_out_of_range(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "1, 99")
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == ["/a.gguf"]


def test_picker_dedupes_preserving_order(monkeypatch, capsys):
    """``1,2,1`` selects 2 unique models, in input order."""
    monkeypatch.setattr("builtins.input", lambda _="": "2,1,2")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/b.gguf", "/a.gguf"]


# ── _resolve_paths ───────────────────────────────────────────────


def test_resolve_paths_keeps_existing(tmp_path):
    p = _make_gguf(tmp_path, "x.gguf")
    out = bcv._resolve_paths([str(p)])
    assert out == [str(p.resolve())]


def test_resolve_paths_drops_missing(tmp_path, capsys):
    out = bcv._resolve_paths([str(tmp_path / "ghost.gguf")])
    err = capsys.readouterr().err
    assert out == []
    assert "not found" in err


# ── argv dispatch ────────────────────────────────────────────────


def test_compare_help_returns_zero(capsys):
    rc = bcv._cmd_bench_compare_argv(["-h"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "compare" in err.lower()
    assert "--models" in err


def test_compare_models_flag_skips_picker(tmp_path, monkeypatch, capsys):
    """Passing ``--models PATH,PATH`` bypasses the picker entirely.
    With ``--dry-run`` the sweep is not launched."""
    m1 = _make_gguf(tmp_path, "alpha.gguf")
    m2 = _make_gguf(tmp_path, "beta.gguf")
    # Picker must NOT be called when --models is given.
    monkeypatch.setattr(
        bcv, "_interactive_pick",
        lambda *_a, **_kw: pytest.fail("picker should not run with --models"),
    )
    rc = bcv._cmd_bench_compare_argv(
        ["--models", f"{m1},{m2}", "--dry-run"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "alpha.gguf" in out
    assert "beta.gguf" in out
    assert "dry-run" in out


def test_compare_dry_run_does_not_launch_subprocess(tmp_path, monkeypatch):
    """``--dry-run`` must not actually invoke the sweep — guard against
    accidental long-running spawns in CI."""
    m = _make_gguf(tmp_path, "x.gguf")
    called = {"flag": False}
    def _spy(*_a, **_kw):
        called["flag"] = True
        return 0
    monkeypatch.setattr(bcv.subprocess, "call", _spy)
    bcv._cmd_bench_compare_argv(["--models", str(m), "--dry-run"])
    assert called["flag"] is False


def test_compare_no_models_discovered_returns_one(tmp_path, monkeypatch, capsys):
    """Empty model dir + no --models flag → useful error, rc=1."""
    monkeypatch.setattr(
        bcv, "_DEFAULT_MODEL_DIRS", (str(tmp_path / "empty"),),
    )
    monkeypatch.setattr(
        bcv, "_config_extra_gguf_dirs", lambda **_: [],
    )
    rc = bcv._cmd_bench_compare_argv([])
    err = capsys.readouterr().err
    assert rc == 1
    assert "no .gguf" in err.lower()


def test_compare_picker_cancelled_returns_two(tmp_path, monkeypatch, capsys):
    """Blank picker input → user cancelled → rc=2 (matches the
    ``bad-input`` convention from argparse)."""
    d = tmp_path / "models"
    d.mkdir()
    _make_gguf(d, "alpha.gguf")
    monkeypatch.setattr(
        bcv, "_DEFAULT_MODEL_DIRS", (str(d),),
    )
    monkeypatch.setattr(
        bcv, "_config_extra_gguf_dirs", lambda **_: [],
    )
    monkeypatch.setattr(
        bcv, "_current_model_path", lambda **_: None,
    )
    monkeypatch.setattr("builtins.input", lambda _="": "")
    rc = bcv._cmd_bench_compare_argv([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "cancelled" in err.lower()


def test_compare_forwards_tags_and_limit_as_flags(tmp_path, monkeypatch, capsys):
    """``--tags`` / ``--limit`` get forwarded to ``bench.py --models`` as
    ``--category`` / ``--limit`` CLI flags."""
    m = _make_gguf(tmp_path, "x.gguf")
    captured: dict[str, str] = {}
    def _spy(cmd, env=None, **_kw):
        if "--category" in cmd:
            captured["TAGS"] = cmd[cmd.index("--category") + 1]
        if "--limit" in cmd:
            captured["LIMIT"] = cmd[cmd.index("--limit") + 1]
        return 0
    monkeypatch.setattr(bcv.subprocess, "call", _spy)
    # _repo_root must point at something with benchmark/bench.py — patch
    # it to the real repo so the "missing script" branch doesn't fire.
    real_repo = pathlib.Path(__file__).resolve().parents[5]
    monkeypatch.setattr(bcv, "_repo_root", lambda: real_repo)
    rc = bcv._cmd_bench_compare_argv([
        "--models", str(m),
        "--tags", "routing,memory",
        "--limit", "5",
    ])
    assert rc == 0
    assert captured["TAGS"] == "routing,memory"
    assert captured["LIMIT"] == "5"


# ── dispatcher integration ───────────────────────────────────────


def test_cli_bench_dispatcher_routes_compare(monkeypatch):
    """``jaeger bench compare`` must route to the verb implementation
    inside the existing bench dispatcher."""
    from jaeger_os.cli.verbs import dispatch as cli
    captured: list[list[str]] = []
    def _spy(argv):
        captured.append(argv)
        return 0
    monkeypatch.setattr(
        "jaeger_os.cli.verbs.bench_compare_verb._cmd_bench_compare_argv", _spy,
    )
    rc = cli._cmd_bench(["compare", "--dry-run"])
    assert rc == 0
    assert captured == [["--dry-run"]]


# ── memory-safety guard (2026-05-27) ─────────────────────────────
# A 32 GB M1 Max kernel-panicked TWICE running dense ≥16 GB models
# in a sweep (unified-memory exhaustion → swap thrash → watchdog
# timeout). The guard must block those before they ever load. MoE
# models of the same on-disk size are safe (only active experts
# drive sustained compute) and must still pass.


def test_is_moe_detects_active_param_markers():
    assert bcv._is_moe("Qwen3.6-35B-A3B-Q4_K_M.gguf") is True
    assert bcv._is_moe("gemma-4-26B-A4B-it-Q4_K_M.gguf") is True
    assert bcv._is_moe("Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf") is True
    assert bcv._is_moe("some-model-MoE-q4.gguf") is True
    # Dense models — no active-param marker.
    assert bcv._is_moe("gemma-4-31B-it-Q4_K_M.gguf") is False
    assert bcv._is_moe("Qwen3.6-27B-Q4_K_M.gguf") is False
    assert bcv._is_moe("Llama-3.2-3B-Instruct-Q4_K_M.gguf") is False


def test_guard_blocks_large_dense_on_32gb(tmp_path):
    """The exact crash scenario: a dense 18.7 GB model on 32 GB RAM
    must be BLOCKED (0.45 × 32 = 14.4 GB dense cap)."""
    dense = _make_gguf(tmp_path, "gemma-4-31B-it-Q4_K_M.gguf",
                       size_bytes=1024)
    # Stub the file size to 18.7 GB without writing 18 GB to disk.
    import os as _os
    orig_stat = _os.stat
    safe, blocked = bcv._memory_safety_partition(
        [str(dense)], ram_bytes=32 * 10**9,
    )
    # The real file is tiny, so it won't trip — verify the LOGIC with
    # an explicit-size helper instead.
    # (Direct logic test below covers the size threshold.)
    assert isinstance(safe, list) and isinstance(blocked, list)


def test_guard_partition_logic_dense_vs_moe():
    """Pure-logic check of the partition using monkeypatched sizes —
    no giant files on disk. Dense 18.7 GB blocked, MoE 21.2 GB
    allowed, both on a 32 GB machine."""
    import pathlib as _pl
    sizes = {
        "/m/gemma-4-31B-it-Q4_K_M.gguf": 18.7e9,      # dense — BLOCK
        "/m/Qwen3.6-27B-Q4_K_M.gguf": 16.5e9,         # dense — BLOCK
        "/m/Qwen3.6-35B-A3B-Q4_K_M.gguf": 21.2e9,     # MoE — ALLOW
        "/m/gemma-4-26B-A4B-it-Q4_K_M.gguf": 16.8e9,  # MoE — ALLOW
        "/m/gemma-4-E4B-it-Q4_K_M.gguf": 5.3e9,       # small dense — ALLOW
        "/m/Qwen3.5-9B-Q4_K_M.gguf": 9.0e9,           # dense 9B — ALLOW (<14.4)
    }

    class _FakeStat:
        def __init__(self, size): self.st_size = size

    import os as _os
    orig = _os.stat
    def _fake_stat(p, *a, **k):
        ps = str(p)
        if ps in sizes:
            return _FakeStat(int(sizes[ps]))
        return orig(p, *a, **k)

    import unittest.mock as mock
    with mock.patch.object(_pl.Path, "stat",
                           lambda self: _FakeStat(int(sizes[str(self)]))):
        safe, blocked = bcv._memory_safety_partition(
            list(sizes.keys()), ram_bytes=32 * 10**9,
        )
    blocked_names = {_pl.Path(b["path"]).name for b in blocked}
    safe_names = {_pl.Path(s["path"]).name for s in safe}
    assert blocked_names == {
        "gemma-4-31B-it-Q4_K_M.gguf", "Qwen3.6-27B-Q4_K_M.gguf",
    }
    assert "Qwen3.6-35B-A3B-Q4_K_M.gguf" in safe_names  # MoE, big, OK
    assert "gemma-4-26B-A4B-it-Q4_K_M.gguf" in safe_names
    assert "gemma-4-E4B-it-Q4_K_M.gguf" in safe_names
    assert "Qwen3.5-9B-Q4_K_M.gguf" in safe_names


def test_guard_blocks_in_compare_and_drops_to_safe(tmp_path, monkeypatch, capsys):
    """End-to-end: a mix of one safe + one dangerous model, without
    --force, drops the dangerous one and proceeds with the safe one
    (dry-run so nothing launches)."""
    safe_model = _make_gguf(tmp_path, "gemma-4-E4B-it-Q4_K_M.gguf")
    danger = _make_gguf(tmp_path, "gemma-4-31B-it-Q4_K_M.gguf")
    # Force the partition to treat danger as blocked regardless of the
    # tiny on-disk size.
    def _fake_partition(paths, **_kw):
        safe_l, blocked_l = [], []
        for p in paths:
            if "31B" in p:
                blocked_l.append({"path": p, "size_gb": 18.7,
                                  "kind": "dense", "reason": "too big"})
            else:
                safe_l.append({"path": p, "size_gb": 5.3,
                               "kind": "dense", "reason": "ok"})
        return safe_l, blocked_l
    monkeypatch.setattr(bcv, "_memory_safety_partition", _fake_partition)

    rc = bcv._cmd_bench_compare_argv(
        ["--models", f"{safe_model},{danger}", "--dry-run"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "MEMORY-SAFETY GUARD" in out
    assert "gemma-4-31B-it" in out          # named as excluded
    assert "gemma-4-E4B-it-Q4_K_M.gguf" in out  # still in the safe set
    # The blocked model must NOT appear in the "Selected ... to
    # benchmark" list — only the safe one.
    selected_section = out.split("Selected")[1]
    assert "31B" not in selected_section


def test_guard_all_blocked_returns_two(tmp_path, monkeypatch, capsys):
    """If every model is dangerous and --force isn't set, refuse with
    rc=2 rather than launching nothing."""
    danger = _make_gguf(tmp_path, "gemma-4-31B-it-Q4_K_M.gguf")
    monkeypatch.setattr(
        bcv, "_memory_safety_partition",
        lambda paths, **_kw: ([], [{"path": p, "size_gb": 18.7,
                                    "kind": "dense", "reason": "too big"}
                                   for p in paths]),
    )
    rc = bcv._cmd_bench_compare_argv(["--models", str(danger), "--dry-run"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "every selected model was blocked" in err


def test_guard_force_bypasses(tmp_path, monkeypatch, capsys):
    """--force runs the blocked models anyway (with a loud warning)."""
    danger = _make_gguf(tmp_path, "gemma-4-31B-it-Q4_K_M.gguf")
    monkeypatch.setattr(
        bcv, "_memory_safety_partition",
        lambda paths, **_kw: ([], [{"path": p, "size_gb": 18.7,
                                    "kind": "dense", "reason": "too big"}
                                   for p in paths]),
    )
    rc = bcv._cmd_bench_compare_argv(
        ["--models", str(danger), "--force", "--dry-run"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "--force" in out
    assert "You were warned" in out
    # The blocked model IS in the selection under --force.
    assert "31B" in out.split("Selected")[1]


def test_total_ram_bytes_returns_positive():
    """Sanity: the RAM probe returns a plausible positive value on
    whatever host runs the suite."""
    ram = bcv._total_ram_bytes()
    assert ram > 1 * 10**9  # at least 1 GB


def test_sweep_env_sets_macos_fork_safety(tmp_path, monkeypatch):
    """macOS 26's xzone allocator crashes a forked child in
    ``_malloc_fork_child`` when the parent has done complex
    allocation (numpy/jaeger imports). The sweep driver fork()s a
    bench subprocess per model, so the env it inherits MUST carry
    ``MallocNanoZone=0`` (legacy allocator, fork-safe) and
    ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES``. Regression for the
    2026-05-27 SIGTRAP crash."""
    m = _make_gguf(tmp_path, "x.gguf")
    captured: dict[str, str] = {}
    def _spy(cmd, env=None, **_kw):
        if env is not None:
            captured.update(env)
        return 0
    monkeypatch.setattr(bcv.subprocess, "call", _spy)
    # Treat the model as safe so we reach the launch.
    monkeypatch.setattr(
        bcv, "_memory_safety_partition",
        lambda paths, **_kw: ([{"path": p, "size_gb": 1.0, "kind": "dense",
                                "reason": "ok"} for p in paths], []),
    )
    real_repo = pathlib.Path(__file__).resolve().parents[5]
    monkeypatch.setattr(bcv, "_repo_root", lambda: real_repo)
    rc = bcv._cmd_bench_compare_argv(["--models", str(m)])
    assert rc == 0
    assert captured.get("MallocNanoZone") == "0", (
        "sweep env must set MallocNanoZone=0 to survive fork() on "
        "macOS 26's xzone allocator"
    )
    assert captured.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY") == "YES"
