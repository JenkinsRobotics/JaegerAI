"""Environment preflight — verify the libraries and system tools a
Jaeger needs, and offer to install whatever is missing.

`pip install jaeger-os` pulls the Python packages, but a few of them
wrap system libraries pip cannot provide — PortAudio for audio I/O,
the macOS toolchain for native builds. This module checks the whole
surface, reports exactly what is missing, and — with the user's
consent — runs the fix and re-verifies:

  • ``jaeger-os --doctor`` prints the full report, then offers to
    install anything missing.
  • a concise pass runs at every boot, so a missing dependency is
    surfaced up front, not mid-conversation.

It never installs anything WITHOUT consent — auto-running `pip`/`brew`
silently is too invasive. ``--doctor`` asks first.
"""

from __future__ import annotations

import importlib
import importlib.util
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class Check:
    """One probed dependency."""

    name: str
    category: str          # voice | vision | external | memory | messaging | system
    ok: bool
    detail: str = ""
    fix: str = ""                       # human-readable fix
    fix_cmd: list[str] = field(default_factory=list)  # runnable argv, when auto-fixable


# Optional Python deps: (import-name, pip-name, category, pip-extra).
# Core deps (pydantic-ai, llama-cpp-python, rich, …) are NOT listed — if
# one were missing the package would fail to import long before this
# module runs, so a Python ImportError is the report in that case.
_OPTIONAL_DEPS: list[tuple[str, str, str, str]] = [
    ("kokoro", "kokoro", "voice", "voice"),
    ("pywhispercpp", "pywhispercpp", "voice", "voice"),
    ("sounddevice", "sounddevice", "voice", "voice"),
    ("scipy", "scipy", "voice", "voice"),
    ("torch", "torch", "vision", "vision"),
    ("transformers", "transformers", "vision", "vision"),
    ("diffusers", "diffusers", "vision", "vision"),
    ("openai", "openai", "external", "external"),
    ("anthropic", "anthropic", "external", "external"),
    ("sentence_transformers", "sentence-transformers", "memory", "memory"),
    ("discord", "discord.py", "messaging", "messaging"),
]


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _check_python_deps() -> list[Check]:
    out: list[Check] = []
    for mod, pip_name, cat, extra in _OPTIONAL_DEPS:
        present = _module_present(mod)
        out.append(Check(
            name=mod, category=cat, ok=present,
            detail="installed" if present else "not installed",
            fix="" if present else f'pip install "jaeger-os[{extra}]"',
            fix_cmd=[] if present
            else [sys.executable, "-m", "pip", "install", pip_name],
        ))
    return out


def _check_audio_backend() -> Check:
    """Audio I/O probe.

    0.3.0: macOS prefers ``avaudio_io`` (PyObjC ``AVAudioEngine``) which
    requires ``pyobjc-framework-AVFoundation``.  When it's available the
    PortAudio dep becomes optional — sounddevice is still in
    ``requirements.txt`` as the cross-platform / fallback path through
    at least one release, but a missing PortAudio doesn't fail the
    preflight on macOS when avaudio is healthy.

    Off-macOS we fall through to the legacy PortAudio probe — sounddevice
    is the only path available there.
    """
    # macOS: try avaudio first.
    if platform.system() == "Darwin":
        try:
            import AVFoundation  # noqa: F401 — PyObjC framework
            # Probe AVAudioEngine class lookup so we know the binding
            # is functional, not just imported.
            _engine_cls = AVFoundation.AVAudioEngine
            assert _engine_cls is not None
            return Check(
                "audio I/O", "system", True,
                "AVAudioEngine ready (PyObjC) — PortAudio not required",
            )
        except Exception as exc:  # noqa: BLE001
            # Fall through to PortAudio check + report the avaudio
            # status as a soft hint in the failure path.
            avaudio_hint = (
                f"avaudio backend unavailable ({exc}); "
                "install with: pip install pyobjc-framework-AVFoundation"
            )
            print(f"[preflight] {avaudio_hint}", file=sys.stderr, flush=True)

    # PortAudio path — the historical 0.2.x probe.
    if not _module_present("sounddevice"):
        return Check("audio I/O", "system", False,
                     "neither AVAudioEngine nor sounddevice available",
                     'pip install "jaeger-os[voice]"',
                     [sys.executable, "-m", "pip", "install", "sounddevice"])
    try:
        import sounddevice  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — native load failure
        has_brew = shutil.which("brew") is not None
        return Check(
            "audio I/O", "system", False,
            f"sounddevice could not load its native library: {exc}",
            "brew install portaudio" if has_brew
            else "install Homebrew (brew.sh), then: brew install portaudio",
            ["brew", "install", "portaudio"] if has_brew else [],
        )
    return Check("audio I/O", "system", True, "PortAudio ready (sounddevice)")


# Keep the old name as an alias so existing callers (tests, dev tools)
# don't break.
_check_portaudio = _check_audio_backend


def _check_binaries() -> list[Check]:
    out = [Check(
        "git", "system", shutil.which("git") is not None,
        "instance versioning",
        "" if shutil.which("git") else "xcode-select --install",
    )]
    if platform.system() == "Darwin":
        for binary in ("osascript", "screencapture"):
            present = shutil.which(binary) is not None
            out.append(Check(
                binary, "system", present,
                "computer-use" if present else "missing — computer_use needs it",
            ))
    return out


def check_environment() -> list[Check]:
    """Probe every optional Python dependency plus the system libraries
    and binaries. Returns one :class:`Check` per item."""
    return (_check_python_deps()
            + [_check_portaudio()]
            + _check_binaries()
            + [_check_install_method()])


def _check_install_method() -> Check:
    """Advisory: flag a plain ``pip install`` on system Python and
    suggest pipx (INST-9). Editable installs and pipx installs both
    pass clean.
    """
    from jaeger_os.core.instance.instance import detect_install_method
    method = detect_install_method()
    if method == "pipx":
        return Check(
            name="install method",
            category="system",
            ok=True,
            detail="installed via pipx (isolated venv).",
        )
    if method == "dev-checkout":
        return Check(
            name="install method",
            category="system",
            ok=True,
            detail="dev checkout (editable / source install).",
        )
    if method == "pip":
        return Check(
            name="install method",
            category="system",
            ok=True,
            detail=(
                "installed via pip — legacy 0.2.2 layout. JROS 0.2.3+ "
                "ships as a git-clone install (the in-tree install.sh / "
                "scripts/install.sh curl one-liner). Re-install via the "
                "curl one-liner so upgrades become `git pull && "
                "./install.sh`."
            ),
        )
    return Check(
        name="install method",
        category="system",
        ok=True,
        detail="install method could not be detected.",
    )


# ── instance-aware checks ──────────────────────────────────────────


def _check_instance_config(layout: object) -> list[Check]:
    """Inspect the instance's config.yaml + model file. These are the
    failures we see most often in practice — a model path that points
    at a file the user moved/renamed, a ctx setting bigger than the
    model was trained for, a config that doesn't parse.

    Each Check is non-fixable (no ``fix_cmd``) — the right action is
    "edit your config.yaml", not "pip install something". The doctor
    still prints them so the user knows where to look."""
    out: list[Check] = []
    root = getattr(layout, "root", None)
    if root is None:
        return out

    import pathlib
    config_path = pathlib.Path(root) / "config.yaml"
    if not config_path.is_file():
        return [Check(
            "config.yaml", "instance", False,
            f"missing — expected at {config_path}",
            "run `./run.sh setup` to create the instance scaffold",
        )]

    # YAML parse — config.yaml is the agent's contract. If it doesn't
    # parse, every later check is meaningless.
    try:
        import yaml
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        return [Check(
            "config.yaml", "instance", False,
            f"could not parse: {type(exc).__name__}: {exc}",
            "edit the file by hand or restore from git",
        )]
    out.append(Check("config.yaml", "instance", True,
                     f"parsed ({config_path})"))

    model_cfg = (cfg.get("model") or {}) if isinstance(cfg, dict) else {}
    model_path = model_cfg.get("path") or model_cfg.get("model_path") or ""
    if not model_path:
        out.append(Check(
            "model.path", "instance", False,
            "not configured — agent has no LLM to call",
            "set `model.path` in config.yaml to a GGUF file",
        ))
    else:
        mp = pathlib.Path(model_path).expanduser()
        if not mp.is_absolute():
            mp = pathlib.Path(root) / mp
        if mp.is_file():
            size_mb = mp.stat().st_size / (1024 * 1024)
            out.append(Check(
                "model.path", "instance", True,
                f"{mp.name} ({size_mb:,.0f} MB)",
            ))
        else:
            out.append(Check(
                "model.path", "instance", False,
                f"file missing: {mp}",
                "fix `model.path` in config.yaml or download the model "
                "with `jaeger-os` model tooling",
            ))

    # ctx — sanity-check, but we can't know n_ctx_train without loading.
    ctx = model_cfg.get("ctx") or model_cfg.get("n_ctx") or 0
    try:
        ctx_int = int(ctx)
    except (TypeError, ValueError):
        ctx_int = 0
    if ctx_int <= 0:
        out.append(Check(
            "model.ctx", "instance", False,
            f"invalid ctx: {ctx!r}",
            "set `model.ctx` in config.yaml to a positive integer",
        ))
    elif ctx_int < 2048:
        out.append(Check(
            "model.ctx", "instance", False,
            f"ctx={ctx_int} is unusually small — most prompts won't fit",
            "raise `model.ctx` to at least 4096 (typical: 8192–32768)",
        ))
    else:
        out.append(Check(
            "model.ctx", "instance", True,
            f"ctx={ctx_int}",
        ))

    # Logs dir — created lazily at boot, but if it exists and isn't
    # writable the boot will fail in a confusing place. Check up front.
    logs_dir = getattr(layout, "logs_dir", None) or (pathlib.Path(root) / "logs")
    try:
        pathlib.Path(logs_dir).mkdir(parents=True, exist_ok=True)
        out.append(Check("logs/", "instance", True,
                         f"writable ({logs_dir})"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check(
            "logs/", "instance", False,
            f"could not create / write: {exc}",
            "check filesystem permissions on the instance directory",
        ))

    return out


def _check_memory_integrity(layout: object) -> list[Check]:
    """The on-disk memory files (facts.json, schedules.json,
    board.json) drive most of the agent's behaviour. A corrupted
    JSON file produces confusing mid-conversation errors; checking
    them up front turns "agent fell over" into a one-line message."""
    import json
    import pathlib
    out: list[Check] = []
    memory_dir = getattr(layout, "memory_dir", None)
    if memory_dir is None:
        root = getattr(layout, "root", None)
        if root is None:
            return out
        memory_dir = pathlib.Path(root) / "memory"

    for name in ("facts.json", "board.json", "schedules.json"):
        path = pathlib.Path(memory_dir) / name
        if not path.is_file():
            out.append(Check(
                f"memory/{name}", "memory", True,
                "absent (fresh instance — will be created on first write)",
            ))
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                json.load(fh)
        except Exception as exc:  # noqa: BLE001
            out.append(Check(
                f"memory/{name}", "memory", False,
                f"corrupted: {type(exc).__name__}: {exc}",
                f"back up and recreate: cp {path} {path}.broken && "
                f"echo '{{}}' > {path}",
            ))
            continue
        size_kb = path.stat().st_size / 1024
        out.append(Check(
            f"memory/{name}", "memory", True,
            f"{size_kb:.1f} KB",
        ))
    return out


def _check_plugin_manifests() -> list[Check]:
    """Every bundled plugin's ``plugin.yaml`` must validate against
    the :class:`PluginManifest` schema. A typo'd ``requireds:``
    instead of ``requires:`` would otherwise silently mean "no
    requirements"; this check catches it at doctor time."""
    out: list[Check] = []
    try:
        import pathlib
        from jaeger_os.plugins.manifest import audit_plugin_dir
        plugins_root = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "plugins"
        )
        rows = audit_plugin_dir(plugins_root)
    except Exception as exc:  # noqa: BLE001
        out.append(Check(
            "plugins.manifests", "plugins", False,
            f"audit raised: {type(exc).__name__}: {exc}",
        ))
        return out

    bad = [r for r in rows if not r.get("ok")]
    if not rows:
        out.append(Check(
            "plugins.manifests", "plugins", True,
            "0 plugins discovered (empty plugins/ dir)",
        ))
        return out
    if bad:
        out.append(Check(
            "plugins.manifests", "plugins", False,
            f"{len(bad)} of {len(rows)} manifests failed validation: "
            + "; ".join(
                f"{r['name']}: {r['errors'][0]}"
                for r in bad[:3]
            ),
            "fix the manifest fields named in the error and re-run",
        ))
    else:
        out.append(Check(
            "plugins.manifests", "plugins", True,
            f"{len(rows)} manifest(s) validated",
        ))
    return out


def _check_tool_registry() -> list[Check]:
    """Every name in CORE / LEAN_CORE must resolve to a real
    registered tool. A rename or accidental deletion that the lean-
    surface filter silently hides would mis-route every routing turn.

    Plus a roll-up row: "registered N, visible M, hidden K, unavailable U".
    That single line is how the operator decides whether the surface
    has bloated, whether availability is filtering something they
    expected, or whether a recent skill load actually widened the
    visible set.

    The CORE / LEAN_CORE names are the *agent-facing* names produced
    by ``@register_tool_from_function`` wrappers in
    ``jaeger_os.main.boot_for_tui``, not the function symbols in
    ``jaeger_os.agent.tools.__init__``. So we need the LIVE agent
    registry, which only exists after a boot.

    When no agent is booted (the common case — doctor is meant to be
    runnable cheaply), we report a single ``not checked`` row rather
    than a forest of false negatives. A run that booted the agent
    earlier in the process gets the real check.
    """
    out: list[Check] = []
    try:
        from jaeger_os.agent.skill_registry.toolsets import CORE, LEAN_CORE, tool_visible
    except Exception as exc:  # noqa: BLE001
        out.append(Check(
            "tools.registry", "runtime", False,
            f"could not import toolset config: {exc}",
        ))
        return out

    # Discover the agent's registered tools — Phase-9 stores them on
    # the pipeline dict's ``agent`` (when booted via boot_for_tui).
    registered: dict[str, Any] | None = None
    try:
        from jaeger_os.main import _pipeline
        agent = _pipeline.get("agent")
        if agent is not None and hasattr(agent, "_function_toolset"):
            registered = dict(agent._function_toolset.tools)
    except Exception:  # noqa: BLE001
        registered = None

    if registered is None:
        out.append(Check(
            "tools.registry", "runtime", True,
            "not checked (no booted agent — run from inside a TUI session "
            "to verify name resolution)",
        ))
        return out

    for label, names in (("CORE", CORE), ("LEAN_CORE", LEAN_CORE)):
        missing_names = sorted(n for n in names if n not in registered)
        if missing_names:
            out.append(Check(
                f"tools.{label}", "runtime", False,
                f"unresolved names: {missing_names}",
                "rename / re-register the missing tools, or update toolsets.py",
            ))
        else:
            out.append(Check(
                f"tools.{label}", "runtime", True,
                f"{len(names)} tools resolve",
            ))

    # Surface counts — the operator-facing one-liner.
    total = len(registered)
    visible = sum(1 for n in registered if tool_visible(n))
    hidden = total - visible
    unavailable = 0
    for tool in registered.values():
        if hasattr(tool, "is_available") and not tool.is_available():
            unavailable += 1
    out.append(Check(
        "tools.surface", "runtime", True,
        f"registered {total}, visible {visible}, hidden {hidden}, "
        f"unavailable {unavailable}",
    ))
    return out


def _check_skills_health(layout: object) -> list[Check]:
    """Every discoverable skill must have a parseable SKILL.md.
    Malformed YAML frontmatter is the most common failure (a stray
    tab, a missing colon) — a doctor that catches it saves the user
    a confusing skill-loader stacktrace later."""
    out: list[Check] = []
    try:
        from jaeger_os.agent.skill_registry.skill_loader import discover_skills
        skills = list(discover_skills(layout))
    except Exception as exc:  # noqa: BLE001
        out.append(Check(
            "skills", "skills", False,
            f"discovery raised: {type(exc).__name__}: {exc}",
        ))
        return out
    if not skills:
        out.append(Check(
            "skills", "skills", True,
            "0 discovered (fresh instance — run `reload_skills` once a "
            "skill is authored)",
        ))
        return out
    out.append(Check(
        "skills", "skills", True,
        f"{len(skills)} skill(s) discovered",
    ))
    return out


def check_instance(layout: object) -> list[Check]:
    """Full doctor including environment + instance config
    + memory integrity + tool registry + skills health. Use this
    when ``--doctor`` runs against an explicit instance, the bare
    :func:`check_environment` when no instance is bound (pre-setup).

    The historical surface (env + instance-config) is preserved; the
    new checks append in their own categories so older callers reading
    just env / instance see the same rows they did before."""
    return (
        check_environment()
        + _check_instance_config(layout)
        + _check_memory_integrity(layout)
        + _check_tool_registry()
        + _check_plugin_manifests()
        + _check_skills_health(layout)
    )


def missing(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok]


def fixable(checks: list[Check]) -> list[list[str]]:
    """The de-duplicated set of runnable fix commands for the missing
    checks — what :func:`install_missing` would run."""
    seen: set[tuple[str, ...]] = set()
    cmds: list[list[str]] = []
    for c in missing(checks):
        if c.fix_cmd:
            key = tuple(c.fix_cmd)
            if key not in seen:
                seen.add(key)
                cmds.append(c.fix_cmd)
    return cmds


def install_missing(checks: list[Check]) -> list[Check]:
    """Run the fix command for each auto-fixable missing check, then
    re-probe and return a fresh environment report. The caller is
    responsible for getting the user's consent first."""
    for cmd in fixable(checks):
        print(f"  → {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(cmd, check=False, timeout=900)
        except Exception as exc:  # noqa: BLE001
            print(f"    failed: {type(exc).__name__}: {exc}", flush=True)
    importlib.invalidate_caches()
    return check_environment()


def format_report(checks: list[Check]) -> str:
    """A grouped, human-readable report for ``jaeger-os --doctor``."""
    lines = ["", "  Jaeger-OS — environment check", ""]
    for category in ("instance", "daemon", "runtime", "memory", "plugins", "skills",
                     "voice", "vision", "external", "messaging", "system"):
        group = [c for c in checks if c.category == category]
        if not group:
            continue
        lines.append(f"  {category}")
        for c in group:
            mark = "✓" if c.ok else "✗"
            lines.append(f"    {mark} {c.name:<22}{c.detail}")
        lines.append("")
    bad = missing(checks)
    if not bad:
        lines.append("  All dependencies present — the Jaeger is fully operational.")
    else:
        lines.append(f"  {len(bad)} item(s) need attention:")
        for cmd in sorted({c.fix for c in bad if c.fix}):
            lines.append(f"    {cmd}")
    lines.append("")
    return "\n".join(lines)


def boot_warning(checks: list[Check]) -> str:
    """A concise one-block warning for the boot log — empty when the
    environment is fully ready."""
    bad = missing(checks)
    if not bad:
        return ""
    names = ", ".join(c.name for c in bad)
    out = [f"[jaeger] ⚠ {len(bad)} optional dependency issue(s): {names}",
           "[jaeger]   run `jaeger-os --doctor` to install them"]
    return "\n".join(out)


def report_as_json(checks: list[Check]) -> str:
    """Machine-readable doctor report. Stable schema for scripting,
    monitoring agents, or feeding the result back to the agent itself
    via a tool call. ``ok`` rolls up across the whole report so the
    caller can branch on a single boolean."""
    import json
    bad = missing(checks)
    payload = {
        "ok": not bad,
        "total": len(checks),
        "passed": len(checks) - len(bad),
        "failed": len(bad),
        "checks": [
            {
                "name": c.name,
                "category": c.category,
                "ok": c.ok,
                "detail": c.detail,
                "fix": c.fix,
                "fix_cmd": list(c.fix_cmd) if c.fix_cmd else [],
            }
            for c in checks
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
