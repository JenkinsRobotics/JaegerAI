"""Slash-command parser for the Jaeger-OS TUI.

Hermes-agent style: lines starting with ``/`` are commands, not
prompts to the agent. The handler set covers admin operations the
agent loop shouldn't waste tokens on — model + instance management,
help, quit. Anything else routes to ``jaeger_os.main.run_command``.

Handlers receive (ctx, args_str). ``args_str`` is the remainder of
the line after the command name; handlers split it themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .theme import ACCENT_BOLD


@dataclass(frozen=True)
class SlashCommand:
    name: str                                                    # without leading slash
    summary: str
    handler: Callable[["SlashContext", str], "SlashResult"]


@dataclass
class SlashContext:
    """What a slash handler can poke at."""

    console: Console
    instance_dir: object  # pathlib.Path
    # The owning TUI instance — needed by handlers that want to mutate
    # session state (instance switch, model swap). None is allowed so
    # tests / banner-only flows don't have to construct a fake TUI.
    tui: Any = None
    facts: dict[str, str] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SlashResult:
    """Return shape — ``quit=True`` ends the REPL; ``message`` is printed.

    ``extras`` is a side-channel for handlers that need to tell the REPL
    something specific (e.g. ``{"goal_just_set": True}`` so the REPL
    fires the first goal-loop turn immediately). ``frozen=True`` means
    we use a ``MappingProxyType``-wrapped default for safety."""

    quit: bool = False
    message: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


# ── Handlers ─────────────────────────────────────────────────────────


# Slash commands grouped for the `/help` menu — hermes-style
# categorized list. A command absent here still shows under "Other"
# (see _help) so a new SlashCommand is never silently undocumented.
_HELP_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Session",          ("help", "status", "peek", "statusbar", "usage",
                           "config", "verbose", "reboot", "shutdown", "quit")),
    ("Conversation",     ("new", "history", "copy", "save", "undo", "retry",
                          "steer", "busy", "stop", "reset")),
    ("Model & Tools",    ("model", "models", "download", "runtime", "tools", "voice")),
    ("Instances",        ("instance", "instances", "factoryreset")),
    ("Skills & Tasks",   ("skills", "deepthink", "board", "goal")),
    ("Memory & Plugins", ("facts", "plugins")),
)


def _help(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Render the slash-command menu, categorized — hermes-style."""
    c = ctx.console
    width = 50

    def _row(cmd: SlashCommand) -> Text:
        line = Text("    ")
        line.append(f"/{cmd.name}".ljust(14), style=ACCENT_BOLD)
        line.append("  ")
        line.append(cmd.summary, style="dim")
        return line

    c.print()
    c.print(Text("┌" + "─" * width + "┐", style=ACCENT_BOLD))
    c.print(Text("│" + "Jaeger-OS · slash commands".center(width) + "│",
                 style=ACCENT_BOLD))
    c.print(Text("└" + "─" * width + "┘", style=ACCENT_BOLD))

    seen: set[str] = set()
    for category, names in _HELP_CATEGORIES:
        c.print()
        c.print(Text(f"  ── {category} ──", style="bold dim"))
        for name in names:
            cmd = _BY_NAME.get(name)
            if cmd is not None:
                seen.add(name)
                c.print(_row(cmd))

    extras = [cmd for cmd in REGISTRY if cmd.name not in seen]
    if extras:
        c.print()
        c.print(Text("  ── Other ──", style="bold dim"))
        for cmd in extras:
            c.print(_row(cmd))

    c.print()
    c.print(Text("  Tip: just type to chat — slash (/) is only for commands.",
                 style="dim"))
    c.print()
    return SlashResult()


def _quit(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    return SlashResult(quit=True, message="Bye.")


def _tools(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    from .status import TOOL_GROUPS, _format_tool_group
    for name, tools in TOOL_GROUPS.items():
        ctx.console.print(_format_tool_group(name, tools))
    return SlashResult()


def _facts(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List stored facts from jaeger's memory layer."""
    from jaeger_os.core.memory import memory as memory_mod
    try:
        rows = memory_mod.list_facts()
    except RuntimeError as exc:
        ctx.console.print(f"[yellow]facts unavailable: {exc}[/]")
        return SlashResult()
    if not rows:
        ctx.console.print("[dim]No facts saved yet.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Value")
    for k, v in sorted(rows.items()):
        table.add_row(k, v[:120] + ("…" if len(v) > 120 else ""))
    ctx.console.print(table)
    return SlashResult()


def _reset(ctx: SlashContext, args: str) -> SlashResult:
    """Alias for /new — clear the in-process conversation history."""
    return _new(ctx, args)


# ── Instance management ─────────────────────────────────────────────


def _instance(ctx: SlashContext, args: str) -> SlashResult:
    """``/instance`` — show active. ``/instance <name>`` — hot-switch."""
    target = args.strip()
    if not target:
        ctx.console.print(f"[bold]Active instance:[/] {ctx.instance_dir}")
        return SlashResult()
    if ctx.tui is None:
        ctx.console.print(
            "[yellow]Hot-switch unavailable in this TUI context.[/] "
            "Restart with `--instance " + target + "`."
        )
        return SlashResult()
    return _do_switch_instance(ctx, target)


def _instances(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List every discoverable instance with its identity + status."""
    from jaeger_os.main import _list_instances
    from jaeger_os.core.instance.schemas import Identity, load_yaml
    rows = _list_instances()
    if not rows:
        ctx.console.print("[dim]No instances found.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Identity")
    table.add_column("Voice")
    table.add_column("Path")
    current_path = str(ctx.instance_dir)
    for name, path, has_manifest in rows:
        marker = " *" if str(path) == current_path else ""
        if has_manifest:
            try:
                ident = load_yaml(path / "identity.yaml", Identity)
                ident_cell = f"{ident.name} — {ident.role[:50]}"
                voice = ident.voice_id or "(default)"
            except Exception as exc:  # noqa: BLE001
                ident_cell = f"(unreadable: {exc!s:.40})"
                voice = "—"
        else:
            ident_cell = "(no manifest — incomplete)"
            voice = "—"
        table.add_row(name + marker, ident_cell, voice, str(path))
    ctx.console.print(table)
    ctx.console.print(
        "[dim]Switch with [bold]/instance <name>[/]. "
        "`*` marks the active instance.[/]"
    )
    return SlashResult()


def _do_switch_instance(ctx: SlashContext, name: str) -> SlashResult:
    """Hot-switch the TUI to a different instance. Tears down the
    current llama-cpp client + lock, boots the new instance, swaps
    everything on the TUI in place. ~5-10s wall time (Gemma reload)."""
    tui = ctx.tui
    if tui is None:
        return SlashResult(message="No TUI context for switch.")
    try:
        with ctx.console.status(
            f"[bold yellow]switching to instance {name!r}…[/]",
            spinner="dots",
        ):
            tui.switch_instance(name)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Switch failed:[/] {exc}")
        return SlashResult()
    ctx.console.print(
        f"[green]Switched to {name!r}.[/] New instance dir: {tui.instance_dir}"
    )
    return SlashResult()


# ── Model management ────────────────────────────────────────────────

# Cloud providers reachable via `/model use <provider> <model>`. Each
# phones out, needs a real API key, and stores that key under its OWN
# credential name — so switching between providers never clobbers the
# previous one's key.
_CLOUD_PROVIDERS = ("ollama-cloud", "openai", "anthropic", "gemini")
_CLOUD_ALIASES = {
    "ollamacloud": "ollama-cloud", "cloud": "ollama-cloud",
    "claude": "anthropic", "google": "gemini",
}
_CLOUD_BASE_URL = {
    "ollama-cloud": "https://ollama.com/v1",
    "openai": "https://api.openai.com/v1",
    # Google Gemini's OpenAI-compatible surface — rides the openai path.
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    # Unused by the Anthropic SDK; set so the saved config self-documents.
    "anthropic": "https://api.anthropic.com",
}
_CLOUD_CRED = {
    "ollama-cloud": "ollama_cloud_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
}
# (human label, where-to-get-a-key) — shown by the key prompt.
_CLOUD_KEY_HINT = {
    "ollama-cloud": ("Ollama Cloud", "ollama.com → Settings → API keys"),
    "openai": ("OpenAI", "platform.openai.com/api-keys"),
    "anthropic": ("Anthropic", "console.anthropic.com → Settings → API Keys"),
    "gemini": ("Google Gemini", "aistudio.google.com/apikey"),
}
# An example model id per provider — shown when no model is given.
_CLOUD_EXAMPLE = {
    "ollama-cloud": "qwen3.5:397b",
    "openai": "gpt-4o",
    "anthropic": "claude-opus-4-7",
    "gemini": "gemini-2.5-flash",
}


def _brain_line(cfg: Any, client: Any) -> str:
    """One-line description of the active brain."""
    ext = getattr(cfg, "external_model", None) if cfg else None
    if (ext is not None and ext.enabled
            and getattr(client, "kind", "local") == "external"):
        return f"[cyan]external · {ext.provider}[/] · {ext.model}"
    if cfg is not None:
        return (f"[cyan]local · llama-cpp[/] · "
                f"{Path(str(cfg.model.model_path)).name}")
    return "[yellow]no active pipeline[/]"


def _model(ctx: SlashContext, args: str) -> SlashResult:
    """Show or switch the agent's brain.

       /model                          interactive model picker
       /model list                     print every model as text
       /model use local [name]         a local .gguf, in-process
       /model use ollama <name>        a local Ollama server
       /model use lmstudio <name>      a local LM Studio server
       /model use ollama-cloud <name>  Ollama Cloud (prompts for a key)
       /model use openai <model>       OpenAI API (prompts for a key)
       /model use anthropic <model>    Claude via the Anthropic API
       /model use gemini <model>       Google Gemini API
    """
    parts = args.split()
    if parts and parts[0].lower() == "use":
        return _model_use(ctx, parts[1:])
    if parts and parts[0].lower() in ("list", "ls", "all"):
        return _model_list(ctx)
    return _model_picker(ctx)


def _resolve_cloud_key(ctx: SlashContext) -> str:
    """The stored external-model API key, if any — used to discover the
    Ollama Cloud catalogue. Empty string when none is configured."""
    try:
        from jaeger_os.core.models.external_model import resolve_api_key
        from jaeger_os.core.instance.instance import InstanceLayout
        from jaeger_os.main import _pipeline
        ext = getattr(_pipeline.get("config"), "external_model", None)
        if ext is None:
            return ""
        layout = InstanceLayout(root=Path(str(ctx.instance_dir)))
        return resolve_api_key(ext, layout) or ""
    except Exception:  # noqa: BLE001
        return ""


# Stage-2 row that lets the user type any model name — appended to every
# cloud provider's model list so "I want a different one than the curated
# / recent suggestions" is always one keystroke away.
_TYPE_A_MODEL_LABEL = "✎ Type a different model…"


def _merge_models(*sources: Any) -> list[str]:
    """Concatenate model-name iterables in order, deduping by exact match."""
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        for name in src or ():
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _build_providers_list(
    found: dict[str, Any], ext_cfg: Any | None,
    *, layout: Any = None,
) -> list[dict[str, Any]]:
    """Build the stage-1 provider list for the Hermes-style ``/model`` picker.

    Same shape as Hermes's provider catalogue — each entry is a dict with
    ``slug``, ``name``, optional ``models`` (display-name strings),
    optional ``total_models``, optional ``is_current``, and optional
    ``type_a_model`` (True for cloud providers whose catalogue is empty,
    so Enter on them prompts the user to type a model name).

    Cloud providers (ollama-cloud, openai, anthropic, gemini) merge:
      ``user-history ∪ live-discovery ∪ curated-fallback``
    and append a ``✎ Type a different model…`` row, so a one-off paste
    becomes a one-click pick next time *and* a different one stays
    reachable. ``layout`` (when supplied) is what reads the per-instance
    history file.
    """
    current_provider = (
        ext_cfg.provider if ext_cfg is not None and getattr(ext_cfg, "enabled", False)
        else "local"
    )
    providers: list[dict[str, Any]] = []

    # llama.cpp (in-process) — Jaeger registry + every GGUF on disk
    # (incl. ones LM Studio downloaded). De-dup by display name.
    local_names: list[str] = []
    seen: set[str] = set()
    for m in found.get("jaeger", []) or []:
        if m.get("path") and m["name"] not in seen:
            seen.add(m["name"])
            local_names.append(m["name"])
    for m in found.get("local_gguf", []) or []:
        if m["name"] not in seen:
            seen.add(m["name"])
            local_names.append(m["name"])
    if local_names:
        providers.append({
            "slug": "local",
            "name": "llama.cpp (in-process)",
            "models": local_names,
            "is_current": current_provider == "local",
        })

    # Ollama — local HTTP server
    ollama = found.get("ollama") or {}
    if ollama.get("online") and ollama.get("models"):
        providers.append({
            "slug": "ollama",
            "name": "Ollama",
            "models": [m["name"] for m in ollama["models"]],
            "is_current": current_provider == "ollama",
        })

    # LM Studio — local HTTP server
    lmstudio = found.get("lmstudio") or {}
    if lmstudio.get("online") and lmstudio.get("models"):
        providers.append({
            "slug": "lmstudio",
            "name": "LM Studio",
            "models": [m["name"] for m in lmstudio["models"]],
            "is_current": current_provider == "lmstudio",
        })

    # Lazy imports keep the module load cheap when no picker is opened.
    try:
        from jaeger_os.core.models.external_model_history import recent_models
    except Exception:  # noqa: BLE001
        def recent_models(*_a, **_k):  # type: ignore[no-redef]
            return []
    try:
        from jaeger_os.core.models.model_discovery import (
            ANTHROPIC_CURATED,
            GEMINI_CURATED,
            OLLAMA_CLOUD_CURATED,
            OPENAI_CURATED,
        )
    except Exception:  # noqa: BLE001
        OLLAMA_CLOUD_CURATED = ()  # type: ignore[assignment]
        OPENAI_CURATED = ()         # type: ignore[assignment]
        ANTHROPIC_CURATED = ()      # type: ignore[assignment]
        GEMINI_CURATED = ()         # type: ignore[assignment]

    def _cloud_entry(slug: str, name: str, *, live: list[str] | None = None,
                     curated: tuple[str, ...] = ()) -> dict[str, Any]:
        history = recent_models(layout, slug) if layout is not None else []
        models = _merge_models(history, live or [], curated)
        entry: dict[str, Any] = {
            "slug": slug, "name": name,
            "is_current": current_provider == slug,
        }
        if models:
            entry["models"] = models + [_TYPE_A_MODEL_LABEL]
        else:
            entry["type_a_model"] = True
        return entry

    cloud_live = [m["name"] for m in (found.get("ollama_cloud") or {}).get("models") or []]
    providers.append(_cloud_entry(
        "ollama-cloud", "Ollama Cloud",
        live=cloud_live, curated=OLLAMA_CLOUD_CURATED,
    ))
    providers.append(_cloud_entry("openai",    "OpenAI",    curated=OPENAI_CURATED))
    providers.append(_cloud_entry("anthropic", "Anthropic", curated=ANTHROPIC_CURATED))
    providers.append(_cloud_entry("gemini",    "Google",    curated=GEMINI_CURATED))

    return providers


def _model_picker(ctx: SlashContext) -> SlashResult:
    """The interactive ``/model`` picker — a Hermes-style two-stage drill
    (Stage 1 picks a provider, Stage 2 picks a model under it). Enter
    drills / commits; ``← Back`` returns to Stage 1; Cancel / Esc closes."""
    from pathlib import Path

    from jaeger_os.core.models.model_discovery import discover_all
    from jaeger_os.main import _pipeline
    from .picker import _PICKER_TYPE_A_MODEL, pick_provider_model

    cfg = _pipeline.get("config")
    cloud_key = _resolve_cloud_key(ctx)
    with ctx.console.status("[dim]scanning for models…[/]"):
        found = discover_all(cloud_key)
    ext = getattr(cfg, "external_model", None)
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=Path(str(ctx.instance_dir)))
    providers = _build_providers_list(found, ext, layout=layout)
    if not providers:
        return SlashResult(message="[yellow]No models found.[/]")

    if ext is not None and getattr(ext, "enabled", False) and getattr(ext, "model", ""):
        cur_provider = ext.provider
        cur_model = ext.model
    else:
        cur_provider = "local"
        cur_model = (
            Path(str(cfg.model.model_path)).name
            if cfg is not None and getattr(cfg, "model", None) else ""
        )

    result = pick_provider_model(
        providers,
        current_provider=cur_provider,
        current_model=cur_model,
    )
    if result is None:
        return SlashResult(message="[dim]model unchanged.[/]")
    slug, model = result
    if model is _PICKER_TYPE_A_MODEL or model == _TYPE_A_MODEL_LABEL:
        try:
            typed = ctx.console.input(f"  {slug} model: ").strip()
        except (EOFError, KeyboardInterrupt):
            return SlashResult(message="[dim]cancelled.[/]")
        if not typed:
            return SlashResult(message="[yellow]No model entered.[/]")
        return _model_use(ctx, [slug, typed])
    # Local picks display a name but the switch argument is the GGUF path
    # when the model came from the disk scan (the on-disk file the agent
    # loads in-process), or the registry name when it's a Jaeger-registered
    # model. Map back here.
    if slug == "local":
        path_map = {
            m["name"]: m["path"]
            for m in (found.get("local_gguf") or [])
            if m.get("path")
        }
        return _model_use(ctx, ["local", path_map.get(model, model)])
    return _model_use(ctx, [slug, model])


def _model_list(ctx: SlashContext) -> SlashResult:
    """Print every model as a plain text catalogue (``/model list``)."""
    from jaeger_os.core.models.model_discovery import discover_all
    from jaeger_os.main import _pipeline
    cfg = _pipeline.get("config")
    ctx.console.print(
        f"[bold]Active brain:[/] {_brain_line(cfg, _pipeline.get('client'))}"
    )
    with ctx.console.status("[dim]scanning for models…[/]"):
        found = discover_all(_resolve_cloud_key(ctx))

    # JROS in-process GGUF models.
    ctx.console.print("\n[bold]JROS models[/] [dim]· registered, in-process[/]")
    for m in found["jaeger"]:
        dot = "[green]●[/]" if m.get("path") else "[dim]○[/]"
        size = f"{m['size_gb']} GB" if m.get("size_gb") else ""
        ctx.console.print(f"  {dot} {m['name']:30s} {size:9s} "
                          f"[dim]{m.get('status', '')}[/]")
    ctx.console.print("  [dim]download:  /download <name>[/]")

    # Every .gguf on disk JROS can load in-process — repo models/, the
    # JROS cache, LM Studio's folder. All selectable with /model use local.
    local = found.get("local_gguf", [])
    if local:
        ctx.console.print(
            f"\n[bold]Local GGUF files[/] [dim]· {len(local)} on disk, "
            "loadable in-process[/]")
        for m in local:
            sz = f"{m['size_gb']} GB" if m.get("size_gb") else ""
            ctx.console.print(
                f"  [green]●[/] {m['name']:42s} {sz:9s} "
                f"[dim]{m.get('source', '')}[/]")
        ctx.console.print("  [dim]switch:  /model use local <name>[/]")

    # Local Ollama + LM Studio servers (the troubleshooting A/B targets).
    for label, key, switch in (("Ollama", "ollama", "ollama"),
                               ("LM Studio", "lmstudio", "lmstudio")):
        src = found[key]
        status = "[green]online[/]" if src["online"] else "[dim]offline[/]"
        ctx.console.print(
            f"\n[bold]{label}[/] [dim]· {src['endpoint']}[/]  {status}")
        if src["online"] and src["models"]:
            for m in src["models"]:
                sz = f"  {m['size_gb']} GB" if m.get("size_gb") else ""
                ctx.console.print(f"  - {m['name']}{sz}")
            ctx.console.print(f"  [dim]switch:  /model use {switch} <name>[/]")
        elif src["online"]:
            ctx.console.print("  [dim](no models installed)[/]")
        else:
            ctx.console.print(
                f"  [dim]not running — start {label} to A/B against it[/]")

    # Ollama Cloud — the agent phones out when this is the brain. The
    # catalogue shows when an API key is stored; otherwise it's a hint.
    cloud = found.get("ollama_cloud", {})
    cloud_status = ("[green]reachable[/]" if cloud.get("online")
                    else "[dim]no key / unreachable[/]")
    ctx.console.print(
        f"\n[bold]Ollama Cloud[/] [dim]· https://ollama.com/v1[/]  "
        f"{cloud_status}")
    cloud_models = cloud.get("models", [])
    if cloud_models:
        for m in cloud_models:
            ctx.console.print(f"  - {m['name']}")
        ctx.console.print("  [dim]switch:  /model use ollama-cloud <model>[/]")
    else:
        ctx.console.print(
            "  [dim]switch:  /model use ollama-cloud <model>   "
            "(e.g. qwen3.5:397b — prompts for an API key, once)[/]")

    ctx.console.print(
        "\n[dim]switch · on-device:[/]  /model use local"
        "  ·  /model use ollama <name>  ·  /model use lmstudio <name>"
        "\n[dim]switch · cloud API:[/]  /model use ollama-cloud <model>"
        "  ·  /model use openai <model>  ·  /model use anthropic <model>"
        "  ·  /model use gemini <model>"
    )
    return SlashResult()


def _ensure_cloud_key(ctx: SlashContext, cfg: Any, provider: str) -> bool:
    """Make sure the external-model API key is available before we boot
    onto a cloud endpoint. If none resolves, prompt for it with hidden
    input and store it in the instance credential store (0600). Returns
    False if the user supplies nothing.

    The key resolves against ``cfg.external_model.api_key_credential`` —
    which the caller sets to the provider's own credential name — so
    each provider keeps a separate stored key."""
    from jaeger_os.core import credentials as creds
    from jaeger_os.core.models.external_model import resolve_api_key
    from jaeger_os.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=Path(str(ctx.instance_dir)))
    try:
        if resolve_api_key(cfg.external_model, layout):
            ctx.console.print("[dim]✓ API key already configured.[/]")
            return True
    except Exception:  # noqa: BLE001
        pass

    label, where = _CLOUD_KEY_HINT.get(provider, (provider, ""))
    ctx.console.print(
        f"[bold]{label} needs an API key.[/]"
        + (f" [dim]Create one at {where}.[/]" if where else "")
    )
    try:
        key = ctx.console.input(
            "  paste key [dim](hidden)[/]: ", password=True
        ).strip()
    except (EOFError, KeyboardInterrupt):
        ctx.console.print("\n[yellow]Cancelled — brain unchanged.[/]")
        return False
    if not key:
        ctx.console.print("[yellow]No key entered — brain unchanged.[/]")
        return False
    try:
        creds.set_credential(
            layout, cfg.external_model.api_key_credential, key)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't store the key:[/] {exc}")
        return False
    ctx.console.print(
        f"[green]✓ key stored[/] [dim]— "
        f"{layout.root.name}/credentials/"
        f"{cfg.external_model.api_key_credential}, 0600, never logged.[/]"
    )
    return True


def _model_use(ctx: SlashContext, args: list[str]) -> SlashResult:
    """Switch the brain — write external_model into config.yaml, reboot."""
    if ctx.tui is None:
        ctx.console.print("[yellow]Switching the brain needs the TUI.[/]")
        return SlashResult()
    if not args:
        ctx.console.print(
            "[yellow]Usage:[/] /model use local [name] | ollama <name> | "
            "lmstudio <name> | ollama-cloud <model> | openai <model> | "
            "anthropic <model> | gemini <model>")
        return SlashResult()

    from jaeger_os.main import _pipeline
    cfg = _pipeline.get("config")
    if cfg is None:
        ctx.console.print("[yellow]No active pipeline.[/]")
        return SlashResult()

    target = args[0].lower()
    wanted = " ".join(args[1:]).strip()

    if target in ("local", "llama-cpp", "llamacpp", "jaeger"):
        cfg.external_model.enabled = False
        if wanted:
            # Pick a specific .gguf — match the discovered list by name
            # (or take a literal path / registry key), then point the
            # in-process llama-cpp backend at it.
            from jaeger_os.core.models.model_discovery import discover_local_gguf
            chosen = wanted
            for m in discover_local_gguf():
                cand = {m["name"], m["name"].removesuffix(".gguf")}
                if wanted in cand or wanted == m["path"]:
                    chosen = m["path"]
                    break
            cfg.model.model_path = chosen
            summary = f"local · {Path(chosen).name}"
        else:
            summary = f"local · {Path(str(cfg.model.model_path)).name}"
    elif target in ("ollama", "lmstudio", "lm-studio"):
        provider = "ollama" if target == "ollama" else "lmstudio"
        from jaeger_os.core.models.model_discovery import (
            discover_lmstudio, discover_ollama,
        )
        disc = (discover_ollama() if provider == "ollama"
                else discover_lmstudio())
        if not disc["online"]:
            ctx.console.print(
                f"[red]{provider} isn't running[/] at {disc['endpoint']} — "
                "start the server first."
            )
            return SlashResult()
        avail = [m["name"] for m in disc["models"]]
        if not wanted:
            if len(avail) == 1:
                wanted = avail[0]
            else:
                ctx.console.print(
                    f"[yellow]Pick a model:[/] /model use {target} <name>")
                for n in avail:
                    ctx.console.print(f"  - {n}")
                return SlashResult()
        elif avail and wanted not in avail:
            ctx.console.print(
                f"[dim]note: {wanted!r} isn't in {provider}'s list — "
                "trying it anyway[/]")
        cfg.external_model.enabled = True
        cfg.external_model.provider = provider
        cfg.external_model.base_url = (
            "http://localhost:11434/v1" if provider == "ollama"
            else "http://localhost:1234/v1"
        )
        cfg.external_model.model = wanted
        summary = f"external · {provider} · {wanted}"
    elif _CLOUD_ALIASES.get(target, target) in _CLOUD_PROVIDERS:
        provider = _CLOUD_ALIASES.get(target, target)
        if not wanted:
            ctx.console.print(
                f"[yellow]Pick a model:[/] "
                f"[bold]/model use {provider} <model>[/]\n"
                f"[dim]e.g. /model use {provider} "
                f"{_CLOUD_EXAMPLE[provider]}[/]")
            return SlashResult()
        cfg.external_model.enabled = True
        cfg.external_model.provider = provider
        cfg.external_model.base_url = _CLOUD_BASE_URL[provider]
        # Each cloud provider keeps its key under its own credential
        # name, so switching providers never overwrites another's key.
        cfg.external_model.api_key_credential = _CLOUD_CRED[provider]
        cfg.external_model.model = wanted
        # A cloud endpoint needs a real API key — make sure one is on
        # hand (prompting + storing it if not) before we reboot onto it.
        if not _ensure_cloud_key(ctx, cfg, provider):
            return SlashResult()
        summary = f"external · {provider} · {wanted}"
    else:
        ctx.console.print(
            f"[yellow]Unknown target {target!r}[/] — use local / ollama / "
            "lmstudio / ollama-cloud / openai / anthropic / gemini.")
        return SlashResult()

    # Persist to config.yaml, then reboot so make_client rebuilds the brain.
    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.core.instance.schemas import dump_yaml
    name = Path(str(ctx.instance_dir)).name
    layout = InstanceLayout(root=Path(str(ctx.instance_dir)))
    try:
        dump_yaml(layout.config_path, cfg)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't save config:[/] {exc}")
        return SlashResult()
    ctx.console.print(
        f"[yellow]Switching brain → {summary}[/] [dim](rebooting…)[/]")
    try:
        ctx.tui.switch_instance(name)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Reboot failed:[/] {exc}")
        return SlashResult()
    # ``make_client`` silently falls back to the local model when an
    # external endpoint fails its connectivity check. Tell the truth here
    # rather than parroting the requested target — otherwise the user
    # sees "✓ Brain is now external · ollama-cloud · X" while the actual
    # brain is the local gguf the fallback loaded.
    from jaeger_os.main import _pipeline as _pl
    active_client = _pl.get("client")
    targeted_external = target not in ("local", "llama-cpp", "llamacpp", "jaeger")
    actually_local = getattr(active_client, "kind", "local") == "local"
    if targeted_external and actually_local:
        local_name = Path(str(cfg.model.model_path)).name
        ctx.console.print(
            f"[yellow]⚠ Couldn't reach {summary}.[/] "
            f"Fell back to [bold]local · {local_name}[/]. "
            f"[dim]Check the endpoint / credentials, then try again.[/]"
        )
    else:
        ctx.console.print(f"[green]✓ Brain is now {summary}.[/]")
        # Successful switch — remember which external model the user picked so
        # the next /model picker pre-populates this provider's sub-menu with
        # it. Local picks aren't tracked (the GGUF path lives in config).
        if targeted_external and wanted:
            try:
                from jaeger_os.core.models.external_model_history import record_use
                record_use(layout, target, wanted)
            except Exception:  # noqa: BLE001
                pass
    return SlashResult()


def _models(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List EVERY model — the JROS registry, every local ``.gguf`` on
    disk (repo, cache, LM Studio's folder), and the LM Studio / Ollama /
    Ollama Cloud catalogues. Same aggregated view as ``/model list`` —
    ``/models`` is the obvious name, so it shows the whole picture."""
    return _model_list(ctx)


def _runtime(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """One-screen inventory of the local inference engines available to
    this machine — the same view LM Studio's Settings → Runtime panel
    gives: engine, version, install/reach state, the model formats it
    loads. Echoes ``core.runtimes.discover_runtimes`` so adding a new
    engine to the inventory is a one-line change there, not here."""
    from rich.table import Table

    from jaeger_os.core.models.runtimes import discover_runtimes

    with ctx.console.status("[dim]probing runtimes…[/]"):
        runtimes = discover_runtimes()

    ctx.console.print()
    ctx.console.print("[bold]Engines & Frameworks[/]")
    ctx.console.print()

    table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    table.add_column("Engine", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Formats", no_wrap=True)
    table.add_column("Notes")

    available_count = 0
    for rt in runtimes:
        if rt.available:
            available_count += 1
            status = "[green]✓ available[/]"
            version = rt.version or "—"
            notes = rt.description
        else:
            status = "[dim]✗ not installed[/]"
            version = "[dim]—[/]"
            notes = f"[dim]{rt.install_hint or rt.description}[/]"
        table.add_row(
            f"[bold]{rt.display_name}[/]",
            version,
            status,
            ", ".join(rt.formats),
            notes,
        )

    ctx.console.print(table)
    ctx.console.print()
    ctx.console.print(
        f"[dim]{available_count} of {len(runtimes)} runtimes available. "
        "GGUF runs in-process via llama-cpp-python; MLX requires the "
        "``mlx-lm`` wheel; Ollama / LM Studio are HTTP servers.[/]"
    )
    return SlashResult()


def _download(ctx: SlashContext, args: str) -> SlashResult:
    """Download a registered model into the user cache. No-op if the
    file is already cached."""
    name = args.strip()
    if not name:
        ctx.console.print(
            "[yellow]Usage:[/] /download <model-name>.  "
            "Run /models for the catalog."
        )
        return SlashResult()
    from jaeger_os.core.models.model_resolver import MODEL_REGISTRY, download_model
    if name not in MODEL_REGISTRY:
        ctx.console.print(
            f"[red]Unknown model {name!r}.[/] Known: "
            + ", ".join(sorted(MODEL_REGISTRY.keys()))
        )
        return SlashResult()
    try:
        with ctx.console.status(
            f"[bold yellow]downloading {name}…[/]", spinner="dots",
        ):
            path = download_model(name, progress=False)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Download failed:[/] {exc}")
        return SlashResult()
    ctx.console.print(f"[green]Downloaded:[/] {path}")
    return SlashResult()


# ── Plugin management (read-only — actually using a plugin still
#     goes through the corresponding agent tool / CLI) ──────────────


def _plugins(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List bundled plugins (discord, telegram, whisper_stt, etc.)
    with install + credential status, so the user knows what's ready."""
    from jaeger_os.core.tools.plugins import list_plugins
    result = list_plugins()
    plugins = result.get("plugins") or []
    if not plugins:
        ctx.console.print("[dim]No plugins found.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Plugin")
    table.add_column("Status")
    table.add_column("Description")
    for p in plugins:
        desc = (p.get("description") or "").split("\n")[0][:60]
        table.add_row(p["name"], p["status"], desc)
    ctx.console.print(table)
    return SlashResult()


# ── Goal (Claude-Code-style /goal) ──────────────────────────────────


_GOAL_CLEAR_ALIASES = {"clear", "stop", "off", "reset", "none", "cancel"}


# A goal that reads like "build/make/create … a skill/tool" — those want
# Deep Think (autonomous skill authoring with the coder model), not the
# realtime goal loop.
_SKILL_DEV_RE = re.compile(
    r"\b(make|build|create|write|develop|implement|add)\b.{0,40}\b"
    r"(skill|tool|plugin|capability|ability|integration)\b",
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_skill_dev(condition: str) -> bool:
    """True when a goal is in-depth skill development → route to Deep Think."""
    return bool(_SKILL_DEV_RE.search(condition or ""))


def _goal_title(text: str, limit: int = 70) -> str:
    """A short one-line title for a board card built from a goal."""
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()),
                 "goal")
    return first[:limit].strip() or "goal"


def _goal(ctx: SlashContext, args: str) -> SlashResult:
    """``/goal``              show active goal status + most recent eval reason
       ``/goal <condition>``  set a goal — clarifies, then asks whether to
                              start now, queue on the board, or hand it to
                              Deep Think (skill-development goals)
       ``/goal clear``        clear the active goal (aliases: stop, off, reset, none, cancel)
    """
    from jaeger_os.main import clarify_goal, clear_goal, get_goal, set_goal

    body = args.strip()

    # ── Clear path ──
    if body.lower() in _GOAL_CLEAR_ALIASES:
        prior = clear_goal()
        if prior is None:
            ctx.console.print("[dim]No active goal to clear.[/]")
        else:
            ctx.console.print(
                f"[yellow]Cleared goal:[/] {prior.condition!r} "
                f"(ran {prior.turns_evaluated} turn(s), "
                f"{prior.elapsed_s():.0f}s)"
            )
        return SlashResult()

    # ── Status path ──
    if not body:
        goal = get_goal()
        if goal is None:
            ctx.console.print(
                "[dim]No active goal. Set one with [bold]/goal <condition>[/].[/]"
            )
            return SlashResult()
        table = Table(show_header=False, box=None)
        table.add_column(style="bold cyan")
        table.add_column()
        table.add_row("Condition", goal.condition)
        table.add_row("Running for", f"{goal.elapsed_s():.0f}s")
        table.add_row("Turns evaluated", str(goal.turns_evaluated))
        table.add_row("Tokens (eval)", str(goal.tokens_spent))
        table.add_row("Max iterations", str(goal.max_iterations))
        if goal.last_reason:
            table.add_row("Last eval", goal.last_reason)
        if goal.achieved:
            table.add_row("[green]Achieved[/]", "yes")
        ctx.console.print(table)
        return SlashResult()

    # ── Set path: clarify → choose disposition → act ──
    if len(body) > 4000:
        ctx.console.print(
            f"[red]Goal condition too long ({len(body)} chars; max 4000).[/]"
        )
        return SlashResult()

    client = getattr(ctx.tui, "_client", None) if ctx.tui is not None else None

    # 1. Clarify — ask only genuinely-necessary follow-ups.
    questions: list[str] = []
    if client is not None:
        with ctx.console.status("[dim]considering what to ask…[/]",
                                spinner="dots"):
            questions = clarify_goal(client, body)
    answers: list[str] = []
    for q in questions:
        try:
            a = ctx.console.input(f"  [cyan]?[/] {q}\n    ").strip()
        except (EOFError, KeyboardInterrupt):
            a = ""
        if a:
            answers.append(f"{q}  →  {a}")
    condition = body
    if answers:
        condition = body + "\n\nClarifications:\n" + "\n".join(
            f"- {a}" for a in answers
        )

    # 2. Disposition — start now, queue on the board, or hand to Deep Think.
    skill_dev = _looks_like_skill_dev(body)
    if skill_dev:
        ctx.console.print(
            "\n[bold]How should I take this on?[/] "
            "[dim](looks like skill development)[/]\n"
            "  [bold]d[/] — Deep Think: autonomous skill build "
            "[green](recommended)[/]\n"
            "  [bold]s[/] — Start now: work it as a goal loop this session\n"
            "  [bold]b[/] — Board: queue it on the kanban board\n"
            "  [bold]c[/] — Cancel"
        )
        default = "d"
    else:
        ctx.console.print(
            "\n[bold]How should I take this on?[/]\n"
            "  [bold]s[/] — Start now: work it as a goal loop this session "
            "[green](recommended)[/]\n"
            "  [bold]b[/] — Board: queue it on the kanban board\n"
            "  [bold]d[/] — Deep Think: autonomous skill-development mode\n"
            "  [bold]c[/] — Cancel"
        )
        default = "s"
    try:
        choice = (ctx.console.input(f"  choice [{default}]: ").strip().lower()
                  or default)[:1]
    except (EOFError, KeyboardInterrupt):
        choice = "c"

    # 3. Act.
    if choice == "c":
        ctx.console.print("[dim]Goal cancelled.[/]")
        return SlashResult()

    if choice == "b":
        try:
            pri = (ctx.console.input(
                "  priority — high / med / low [med]: ").strip().lower()
                or "med")
        except (EOFError, KeyboardInterrupt):
            pri = "med"
        if pri not in ("high", "med", "low"):
            pri = "med"
        try:
            card = _board_for_ctx(ctx).add(
                _goal_title(body), column="ready", description=condition,
                source="goal", created_by="user", priority=pri,
            )
        except Exception as exc:  # noqa: BLE001
            ctx.console.print(f"[red]Couldn't add to the board:[/] {exc}")
            return SlashResult()
        ctx.console.print(
            f"[green]Queued on the board[/] [{card.id}] "
            f"[dim]({pri} priority, 'ready' column)[/] — see [bold]/board[/]."
        )
        return SlashResult()

    if choice == "d":
        try:
            task = _deep_think_queue(ctx).add(condition, source="user")
        except Exception as exc:  # noqa: BLE001
            ctx.console.print(f"[red]Couldn't queue for Deep Think:[/] {exc}")
            return SlashResult()
        ctx.console.print(
            f"[green]Queued for Deep Think[/] [{task.id}] {task.description}"
        )
        try:
            now = ctx.console.input(
                "  start Deep Think now? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            now = ""
        if now.startswith("y"):
            return SlashResult(extras={"deep_think_start": True})
        ctx.console.print(
            "[dim]Run [bold]/deepthink start[/] when you're ready.[/]"
        )
        return SlashResult()

    # choice == "s" (and the fallback) — start the goal loop now.
    goal = set_goal(condition)
    ctx.console.print(
        f"[green]Goal set:[/] {_goal_title(goal.condition)!r}\n"
        f"[dim]I'll run an evaluator after each turn until it's met or "
        f"{goal.max_iterations} turns elapse. [bold]/goal clear[/] stops it.[/]"
    )
    # The marker the REPL reads to fire the FIRST turn immediately, using
    # the condition itself as the prompt.
    return SlashResult(message="", quit=False, extras={"goal_just_set": True})


# ── Deep Think ──────────────────────────────────────────────────────


def _deep_think_queue(ctx: SlashContext):
    """Build the DeepThinkQueue for the active instance."""
    from jaeger_os.core.background.deep_think import queue_for_layout
    from jaeger_os.core.instance.instance import InstanceLayout
    import pathlib
    layout = InstanceLayout(root=pathlib.Path(str(ctx.instance_dir)))
    return queue_for_layout(layout)


def _deepthink(ctx: SlashContext, args: str) -> SlashResult:
    """``/deepthink``                  show mode + queue status
       ``/deepthink add <task>``       queue a skill-development job
       ``/deepthink list``             list every queued task
       ``/deepthink approve <id>``     approve an agent-proposed task
       ``/deepthink start``            enter Deep Think now (swap to coder model)
       ``/deepthink stop``             (only meaningful mid-loop; Ctrl-C also works)
    """
    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        queue = _deep_think_queue(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Deep Think unavailable:[/] {exc}")
        return SlashResult()

    # ── add ──
    if sub == "add":
        if not rest:
            ctx.console.print("[yellow]Usage:[/] /deepthink add <task description>")
            return SlashResult()
        task = queue.add(rest, source="user")
        ctx.console.print(
            f"[green]Queued[/] [{task.id}] {task.description}\n"
            f"[dim]Run [bold]/deepthink start[/] to work the queue.[/]"
        )
        return SlashResult()

    # ── list ──
    if sub in ("list", "ls"):
        tasks = queue.all_tasks()
        if not tasks:
            ctx.console.print("[dim]Deep Think queue is empty.[/]")
            return SlashResult()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID")
        table.add_column("Status")
        table.add_column("Src")
        table.add_column("Task")
        for tk in tasks:
            status = tk.status
            if tk.status == "pending" and not tk.approved:
                status = "needs-approval"
            table.add_row(tk.id, status, tk.source,
                          tk.description[:60] + ("…" if len(tk.description) > 60 else ""))
        ctx.console.print(table)
        return SlashResult()

    # ── approve ──
    if sub == "approve":
        if not rest:
            ctx.console.print("[yellow]Usage:[/] /deepthink approve <task-id>")
            return SlashResult()
        task = queue.approve(rest)
        if task is None:
            ctx.console.print(f"[red]No task with id {rest!r}.[/]")
        else:
            ctx.console.print(f"[green]Approved[/] [{task.id}] {task.description}")
        return SlashResult()

    # ── start ──
    if sub == "start":
        nxt = queue.next_pending()
        if nxt is None:
            summary = queue.summary()
            if summary["awaiting_approval"]:
                ctx.console.print(
                    f"[yellow]Nothing approved to work.[/] "
                    f"{summary['awaiting_approval']} task(s) await approval — "
                    "use [bold]/deepthink approve <id>[/]."
                )
            else:
                ctx.console.print(
                    "[dim]Deep Think queue is empty. Add a task with "
                    "[bold]/deepthink add <task>[/] first.[/]"
                )
            return SlashResult()
        # Signal the REPL to enter the Deep Think loop.
        return SlashResult(extras={"deep_think_start": True})

    if sub == "stop":
        ctx.console.print(
            "[dim]Deep Think only runs inside its work loop — press "
            "Ctrl-C during the loop to interrupt and return to realtime.[/]"
        )
        return SlashResult()

    # ── status (no subcommand) ──
    summary = queue.summary()
    table = Table(show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Queue total", str(summary["total"]))
    table.add_row("Pending (ready)",
                  str(summary["pending"] - summary["awaiting_approval"]))
    table.add_row("Awaiting approval", str(summary["awaiting_approval"]))
    table.add_row("Done", str(summary["done"]))
    table.add_row("Failed", str(summary["failed"]))
    ctx.console.print(table)
    ctx.console.print(
        "[dim]/deepthink add <task> · /deepthink list · "
        "/deepthink start · Ctrl-C interrupts the loop[/]"
    )
    return SlashResult()


def _board_for_ctx(ctx: SlashContext):
    """Build the kanban Board for the active instance."""
    import pathlib

    from jaeger_os.core.background.board import board_for_layout
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(str(ctx.instance_dir)))
    return board_for_layout(layout)


def _board(ctx: SlashContext, args: str) -> SlashResult:
    """``/board``                  show the kanban board
       ``/board add <title>``      add a card (straight to ready)
       ``/board approve <id>``     approve a proposed card (backlog → ready)
       ``/board done <id>``        mark a card done
       ``/board block <id>``       mark a card blocked
       ``/board move <id> <col>``  move a card to any column
    """
    from jaeger_os.core.background.board import COLUMNS

    parts = args.strip().split(None, 2)
    sub = parts[0].lower() if parts else ""
    try:
        board = _board_for_ctx(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Board unavailable:[/] {exc}")
        return SlashResult()

    # ── add ──
    if sub == "add":
        title = args.strip()[3:].strip()
        if not title:
            ctx.console.print("[yellow]Usage:[/] /board add <card title>")
            return SlashResult()
        card = board.add(title, column="ready", source="user", created_by="user")
        ctx.console.print(f"[green]Added[/] [{card.id}] {card.title} → ready")
        return SlashResult()

    # ── id-taking subcommands ──
    if sub in ("approve", "done", "block", "move"):
        rest = parts[1] if len(parts) > 1 else ""
        if not rest:
            ctx.console.print(f"[yellow]Usage:[/] /board {sub} <card_id>"
                              + (" <column>" if sub == "move" else ""))
            return SlashResult()
        card = board.get(rest)
        if card is None:
            ctx.console.print(f"[red]No card[/] {rest!r}")
            return SlashResult()
        if sub == "approve":
            if card.column != "backlog":
                ctx.console.print(f"[dim]{rest} is already past backlog "
                                  f"({card.column}).[/]")
            else:
                board.move(rest, "ready")
                ctx.console.print(f"[green]Approved[/] {rest} → ready")
        elif sub == "done":
            board.move(rest, "done")
            ctx.console.print(f"[green]Done[/] {rest}")
        elif sub == "block":
            board.move(rest, "blocked")
            ctx.console.print(f"[red]Blocked[/] {rest}")
        else:  # move
            col = parts[2].strip().lower() if len(parts) > 2 else ""
            if col not in COLUMNS:
                ctx.console.print(f"[yellow]Column must be one of:[/] "
                                  f"{', '.join(COLUMNS)}")
            else:
                board.move(rest, col)
                ctx.console.print(f"[green]Moved[/] {rest} → {col}")
        return SlashResult()

    # ── show the board (no subcommand) — five-column grid ──
    from jaeger_os.interfaces.tui.board_view import render_board, render_board_empty_hint
    cards = board.list()
    if not cards:
        ctx.console.print(render_board_empty_hint())
        return SlashResult()
    ctx.console.print(render_board(cards))
    ctx.console.print(
        "[dim]/board add · /board approve <id> · /board done <id> · "
        "/board move <id> <col>[/]"
    )
    return SlashResult()


# ── Lifecycle: shutdown / reboot / factory reset ─────────────────────


def _shutdown(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Shut the Jaeger down cleanly — the REPL's finally block releases
    the instance lock and stops background extensions."""
    return SlashResult(quit=True, message="Shutting down. Goodbye.")


def _reboot(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Reboot the Jaeger — tear the pipeline down and bring it straight
    back up (model, skills, config reloaded) without leaving the TUI."""
    if ctx.tui is None:
        ctx.console.print("[yellow]Reboot isn't available in this context.[/]")
        return SlashResult()
    name = Path(str(ctx.instance_dir)).name
    ctx.console.print(f"[yellow]Rebooting {name}…[/]")
    try:
        ctx.tui.switch_instance(name)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Reboot failed:[/] {exc}")
        return SlashResult()
    ctx.console.print("[green]Rebooted.[/]")
    return SlashResult()


def _factory_reset_instance(root: Path) -> None:
    """Erase an instance back to first-boot state: remove the
    identity/config/manifest trio (so the wizard runs next launch) and
    clear all agent-accumulated state, keeping the empty skeleton dirs."""
    import shutil

    for f in ("identity.yaml", "config.yaml", "manifest.json", ".lock"):
        (root / f).unlink(missing_ok=True)
    for sub in ("skills", "memory", "logs", "credentials",
                "processes", "packaged_skills", "venv"):
        d = root / sub
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


def _factoryreset(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Erase this instance — identity, config, agent-authored skills,
    memory, logs, venv — then exit. The next launch runs first-time
    setup from scratch. Guarded by a typed confirmation."""
    root = Path(str(ctx.instance_dir))
    ctx.console.print(
        f"[bold red]⚠ Factory reset[/] erases the instance at [dim]{root}[/]:\n"
        "  identity · config · agent-authored skills · memory · logs · venv\n"
        "  [dim]The next launch starts from first-time setup.[/]"
    )
    try:
        confirm = input("  Type 'reset' to confirm (anything else cancels): ")
    except (EOFError, KeyboardInterrupt):
        confirm = ""
    if confirm.strip().lower() != "reset":
        ctx.console.print("[dim]Factory reset cancelled.[/]")
        return SlashResult()
    try:
        _factory_reset_instance(root)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Factory reset failed:[/] {exc}")
        return SlashResult()
    return SlashResult(
        quit=True,
        message="Factory reset complete — the next launch runs first-time setup.",
    )


# ── Voice ────────────────────────────────────────────────────────────


_VOICE_FEATURES = {
    "wake": "wake_word", "wakeword": "wake_word", "wake-word": "wake_word",
    "followup": "follow_up", "follow-up": "follow_up", "follow": "follow_up",
    "bargein": "barge_in", "barge-in": "barge_in", "barge": "barge_in",
    "mic": "enabled", "enabled": "enabled",
}
_VOICE_ON_WORDS = {"on", "true", "yes", "1", "enable", "enabled"}


def _voice(ctx: SlashContext, args: str) -> SlashResult:
    """Show or change voice settings.

    `/voice` alone prints the current settings. `/voice on|off` turns
    the always-on mic on or off. `/voice wake|followup|bargein on|off`
    toggles that feature. Every change persists to config.yaml and is
    applied live."""
    tui = ctx.tui
    if tui is None:
        ctx.console.print("[yellow]Voice settings need the TUI.[/]")
        return SlashResult()
    parts = args.split()
    if not parts:
        ctx.console.print(tui.voice_status_text())
        return SlashResult()

    word = parts[0].lower()
    if word in {"on", "off"}:
        ctx.console.print(tui.apply_voice_setting("enabled", word == "on"))
        return SlashResult()
    if word in _VOICE_FEATURES and len(parts) >= 2:
        on = parts[1].lower() in _VOICE_ON_WORDS
        ctx.console.print(tui.apply_voice_setting(_VOICE_FEATURES[word], on))
        return SlashResult()

    ctx.console.print(
        "[yellow]Usage:[/] /voice · /voice on│off · "
        "/voice wake│followup│bargein on│off"
    )
    return SlashResult()


# ── Session info / control ───────────────────────────────────────────


def _status(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Show session info — model, instance, uptime, context, mic."""
    import time as _time
    tui = ctx.tui
    if tui is None:
        ctx.console.print("[yellow]/status needs the TUI.[/]")
        return SlashResult()
    up = _time.perf_counter() - getattr(tui, "_started_at", _time.perf_counter())
    hrs, mins = int(up // 3600), int((up % 3600) // 60)
    mic = "on" if (getattr(tui, "_voice", None) is not None
                   and tui._voice.running) else "off"
    table = Table(show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Model", str(getattr(tui, "model_name", "?")))
    table.add_row("Instance", Path(str(ctx.instance_dir)).name)
    table.add_row("Session", str(getattr(tui, "session_id", "?")))
    table.add_row("Uptime", f"{hrs}h {mins:02d}m")
    table.add_row("Context", f"{getattr(tui, '_context_tokens', 0):,}/"
                             f"{getattr(tui, '_context_max', 0):,}")
    table.add_row("Mic", mic)
    ctx.console.print(table)
    return SlashResult()


def _statusbar(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Toggle the bottom status bar under the input line."""
    tui = ctx.tui
    if tui is None:
        ctx.console.print("[yellow]/statusbar needs the TUI.[/]")
        return SlashResult()
    tui._statusbar_on = not getattr(tui, "_statusbar_on", True)
    ctx.console.print(
        f"[dim]Status bar {'shown' if tui._statusbar_on else 'hidden'}.[/]"
    )
    return SlashResult()


def _quiet(ctx: SlashContext, args: str) -> SlashResult:
    """Toggle visibility of voice-activity prints (the [heard] /
    [skipped] / gate-status lines).  When quiet, the agent
    conversation stays clean; voice activity is hidden but the
    gate decisions still happen.  Operator-requested 2026-06-07
    to make the conversation pane easier to follow during TV /
    movie noise testing.

    /quiet         → toggle
    /quiet on      → hide voice activity
    /quiet off     → show voice activity (default)
    """
    tui = ctx.tui
    if tui is None:
        ctx.console.print("[yellow]/quiet needs the TUI.[/]")
        return SlashResult()
    arg = (args or "").strip().lower()
    if arg == "on":
        tui._quiet_voice = True
    elif arg == "off":
        tui._quiet_voice = False
    elif arg == "":
        tui._quiet_voice = not getattr(tui, "_quiet_voice", False)
    else:
        ctx.console.print(
            "[yellow]Usage:[/] /quiet · /quiet on│off"
        )
        return SlashResult()
    state = "hidden" if tui._quiet_voice else "shown"
    ctx.console.print(
        f"[dim]Voice activity {state} "
        f"({len(getattr(tui, '_voice_activity_log', []))} recent events buffered).[/]"
    )
    return SlashResult()


def _busy(ctx: SlashContext, args: str) -> SlashResult:
    """Show or set what Enter does while the agent is mid-turn.

    ``/busy`` with no argument opens an interactive picker; ``/busy
    <mode>`` sets it directly."""
    tui = ctx.tui
    mode = args.strip().lower()
    if not mode:
        cur = getattr(tui, "_busy_mode", "interrupt") if tui else "interrupt"
        running = getattr(tui, "_turn_running", None)
        if running is not None and running.is_set():
            # A turn is painting the screen — a modal picker would be
            # corrupted; show the modes as text instead.
            return SlashResult(
                message=f"[bold]Busy-input mode[/] — [cyan]{cur}[/]. "
                        "[dim]/busy interrupt│queue│steer to change.[/]")
        from .picker import pick
        choice = pick(
            " Busy-input mode ",
            [
                ("interrupt",
                 "interrupt   stop the running turn, run the new one now"),
                ("queue",
                 "queue       run the new message after the current turn"),
                ("steer",
                 "steer       run the new message as the very next turn"),
            ],
            text=f"current: {cur}  ·  ↑/↓ move · Enter select · Esc cancel",
        )
        if choice is None:
            return SlashResult(message="[dim]busy mode unchanged.[/]")
        mode = choice
    if tui is None or not hasattr(tui, "set_busy_mode"):
        return SlashResult(message="[yellow]/busy needs the TUI.[/]")
    if tui.set_busy_mode(mode):
        return SlashResult(message=f"[green]busy-input mode[/] → {mode}")
    return SlashResult(
        message=f"[yellow]Unknown mode '{mode}'.[/] "
                "Use interrupt, queue, or steer."
    )


def _steer(ctx: SlashContext, args: str) -> SlashResult:
    """Send a message that steers the running turn (or runs now if idle)."""
    text = args.strip()
    if not text:
        return SlashResult(message="[yellow]Usage:[/] /steer <message>")
    tui = ctx.tui
    if tui is None or not hasattr(tui, "_submit_turn"):
        return SlashResult(message="[yellow]/steer needs the TUI.[/]")
    running = getattr(tui, "_turn_running", None)
    if running is not None and running.is_set():
        tui._submit_steer(text)
    else:
        tui._submit_turn("text", text)
    return SlashResult()


def _stop(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Stop every running background process."""
    try:
        from jaeger_os.core import tools as _jt
        listing = _jt.list_background()
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't list background processes:[/] {exc}")
        return SlashResult()
    procs: list = []
    if isinstance(listing, dict):
        for key in ("processes", "running", "background", "items"):
            if isinstance(listing.get(key), list):
                procs = listing[key]
                break
    if not procs:
        ctx.console.print("[dim]No background processes running.[/]")
        return SlashResult()
    from jaeger_os.core import tools as _jt
    stopped = 0
    for p in procs:
        pid = ((p.get("id") or p.get("process_id") or p.get("pid")
                or p.get("name")) if isinstance(p, dict) else p)
        if not pid:
            continue
        try:
            _jt.stop_background(str(pid))
            stopped += 1
        except Exception:  # noqa: BLE001
            pass
    ctx.console.print(f"[green]Stopped {stopped} background process(es).[/]")
    return SlashResult()


def _save(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Save the current conversation to a markdown file in the instance."""
    import time as _time
    try:
        from jaeger_os.main import _DEFAULT_SESSION_KEY, _get_session_history
        history = _get_session_history(_DEFAULT_SESSION_KEY)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't read the conversation:[/] {exc}")
        return SlashResult()
    speaker = str(getattr(ctx.tui, "model_name", "") or "Assistant")
    lines: list[str] = []
    for msg in history or []:
        for part in getattr(msg, "parts", []):
            pk = getattr(part, "part_kind", None)
            content = getattr(part, "content", None)
            if pk == "user-prompt" and content:
                lines.append(f"**User:** {content}")
            elif pk == "text" and content:
                lines.append(f"**{speaker}:** {content}")
    if not lines:
        ctx.console.print("[dim]Nothing to save — the conversation is empty.[/]")
        return SlashResult()
    out_dir = Path(str(ctx.instance_dir)) / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"conversation_{stamp}.md"
    try:
        path.write_text(
            f"# Conversation — {stamp}\n\n" + "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't save:[/] {exc}")
        return SlashResult()
    ctx.console.print(f"[green]Saved[/] [dim]{len(lines)} turns →[/] {path}")
    return SlashResult()


# ── Conversation commands ───────────────────────────────────────────


def _copy_to_clipboard(text: str) -> bool:
    """Best-effort copy to the OS clipboard. True on success."""
    import subprocess
    import sys as _sys
    if _sys.platform == "darwin":
        cmds = [["pbcopy"]]
    elif _sys.platform.startswith("win"):
        cmds = [["clip"]]
    else:
        cmds = [["wl-copy"], ["xclip", "-selection", "clipboard"]]
    for cmd in cmds:
        try:
            subprocess.run(cmd, input=text.encode("utf-8"),
                           check=True, timeout=5)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _new(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Start a fresh session — clear the in-process conversation history
    (episodic memory on disk is untouched)."""
    from jaeger_os.main import reset_session
    dropped = reset_session()
    tui = ctx.tui
    if tui is not None:
        from .status import make_session_id
        tui.session_id = make_session_id()
        tui._turn_count = 0
        tui._context_tokens = 0
        tui._last_answer = ""
    return SlashResult(
        message=f"[green]✦ new session[/] — cleared {dropped} message(s). "
                "[dim]Memory on disk is kept.[/]"
    )


def _history(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Show the recent conversation history inline."""
    from jaeger_os.main import _DEFAULT_SESSION_KEY, _get_session_history
    try:
        history = _get_session_history(_DEFAULT_SESSION_KEY)
    except Exception as exc:  # noqa: BLE001
        return SlashResult(message=f"[red]Couldn't read history:[/] {exc}")
    speaker = str(getattr(ctx.tui, "model_name", "") or "agent")
    rows: list[tuple[str, str]] = []
    for msg in history or []:
        for part in getattr(msg, "parts", []):
            pk = getattr(part, "part_kind", None)
            content = getattr(part, "content", None)
            if pk == "user-prompt" and content:
                rows.append(("you", str(content)))
            elif pk == "text" and content:
                rows.append((speaker, str(content)))
    if not rows:
        return SlashResult(message="[dim]No conversation history yet.[/]")
    ctx.console.print(f"[bold]Conversation[/] [dim]— last "
                      f"{min(len(rows), 16)} of {len(rows)} message(s)[/]")
    for who, text in rows[-16:]:
        one = " ".join(text.split())
        clipped = one[:160] + ("…" if len(one) > 160 else "")
        tag_style = "bold cyan" if who == "you" else ACCENT_BOLD
        line = Text("  ")
        line.append(f"{who}: ", style=tag_style)
        line.append(clipped)
        ctx.console.print(line)
    return SlashResult()


def _copy(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Copy the agent's most recent reply to the system clipboard."""
    text = str(getattr(ctx.tui, "_last_answer", "") or "")
    if not text:
        return SlashResult(message="[yellow]Nothing to copy yet.[/]")
    if _copy_to_clipboard(text):
        return SlashResult(
            message=f"[green]✓ copied[/] [dim]{len(text)} chars to the "
                    "clipboard.[/]")
    return SlashResult(
        message="[yellow]Couldn't reach a clipboard tool[/] "
                "[dim](pbcopy / xclip / wl-copy).[/]")


def _undo(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Drop the last user→assistant exchange from the conversation."""
    from jaeger_os.main import pop_last_exchange
    dropped = pop_last_exchange()
    if dropped is None:
        return SlashResult(message="[dim]Nothing to undo.[/]")
    one = " ".join(dropped.split())
    return SlashResult(
        message=f"[green]↶ undone[/] [dim]— removed: {one[:70]}[/]")


def _retry(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Re-run the last user message — drops the last exchange, re-sends."""
    tui = ctx.tui
    if tui is None or not hasattr(tui, "_submit_turn"):
        return SlashResult(message="[yellow]/retry needs the TUI.[/]")
    from jaeger_os.main import pop_last_exchange
    text = pop_last_exchange()
    if text is None:
        return SlashResult(message="[dim]Nothing to retry.[/]")
    one = " ".join(text.split())
    ctx.console.print(f"[dim]↻ retrying:[/] {one[:80]}")
    tui._submit_turn("text", text)
    return SlashResult()


def _verbose(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Toggle whether the ┊ tool-activity lines are shown."""
    from jaeger_os.main import _pipeline
    new = not _pipeline.get("show_tool_activity", True)
    _pipeline["show_tool_activity"] = new
    return SlashResult(
        message=f"[green]tool activity[/] → {'shown' if new else 'hidden'}")


def _usage(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Show this session's usage — turns, timing, context estimate."""
    from jaeger_os.main import _pipeline
    tui = ctx.tui
    model = str(getattr(tui, "model_name", "")
                or getattr(_pipeline.get("config", None), "instance_name", "?"))
    turns = int(getattr(tui, "_turn_count", 0) or 0)
    last_s = float(getattr(tui, "_last_turn_s", 0.0) or 0.0)
    tok = int(getattr(tui, "_context_tokens", 0) or 0)
    mx = int(getattr(tui, "_context_max", 0) or 0)
    pct = int(tok / mx * 100) if mx else 0
    ctx.console.print("[bold]Session usage[/]")
    ctx.console.print(f"  model        [cyan]{model}[/]")
    ctx.console.print(f"  turns        {turns}")
    ctx.console.print(f"  last turn    {last_s:.1f}s")
    ctx.console.print(
        f"  context      ~{tok:,} / {mx:,} tokens ({pct}%) "
        "[dim](estimate)[/]")
    # If the loaded ctx is well below the model's *native* trained
    # max, surface it so the operator knows headroom is available.
    # llama-cpp-python: ``client.native_ctx_max == n_ctx_train()``.
    try:
        from jaeger_os.main import _pipeline as _pl
        _client = _pl.get("client")
        native = int(getattr(_client, "native_ctx_max", 0) or 0)
        if mx and native and native > mx * 2:
            ctx.console.print(
                f"  [dim]model trained for up to {native:,} tokens — "
                f"raise config.model.ctx (currently {mx:,}) and "
                f"reload to use the headroom.[/]"
            )
    except Exception:  # noqa: BLE001
        pass
    # Tool usage telemetry — most-called tools, with failure counts.
    try:
        from jaeger_os.core.runtime.usage_stats import top_tools
        rows = top_tools(8)
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        ctx.console.print("\n[bold]Top tools[/] [dim]· this instance[/]")
        for r in rows:
            calls, fails = r.get("calls", 0), r.get("failures", 0)
            fail_note = f"  [red]{fails} failed[/]" if fails else ""
            ctx.console.print(
                f"  {r['name']:22s} {calls:4d} call(s)"
                f"  [dim]{r.get('total_s', 0)}s[/]{fail_note}")
    return SlashResult()


def _config(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Show the booted instance's configuration (read-only)."""
    from jaeger_os.main import _pipeline
    cfg = _pipeline.get("config")
    if cfg is None:
        return SlashResult(message="[yellow]No active config.[/]")
    m, ext = cfg.model, cfg.external_model
    perms = getattr(cfg, "permissions", None)
    brain = (f"external · {ext.provider} · {ext.model}"
             if getattr(ext, "enabled", False)
             else f"local · {m.backend} · {m.model_path}")
    ctx.console.print(f"[bold]Config[/] [dim]— instance "
                      f"{cfg.instance_name}[/]")
    ctx.console.print(f"  brain        [cyan]{brain}[/]")
    ctx.console.print(f"  context      {m.ctx} tokens")
    ctx.console.print(f"  permissions  {getattr(perms, 'mode', 'confirm')}")
    ctx.console.print(
        f"  busy input   {getattr(cfg.display, 'busy_input_mode', 'interrupt')}")
    ctx.console.print(
        f"  voice        {'on' if cfg.voice.enabled else 'off'}  "
        f"[dim]wake={cfg.voice.wake_word} "
        f"barge_in={cfg.voice.barge_in}[/]")
    ctx.console.print(
        f"  deep think   idle {cfg.deep_think.auto_idle_minutes}m  "
        f"[dim]coder={cfg.deep_think.coder_model}[/]")
    ctx.console.print("  [dim]edit with /model, /voice, /busy — or "
                      "config.yaml + /reboot.[/]")
    return SlashResult()


def _skills(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List the skills currently loaded — each skill is a tool bundle."""
    try:
        from jaeger_os.core.skills import toolsets as _ts
        summaries = dict(_ts._SKILL_SUMMARY)
        members = dict(_ts._SKILL_TOOLSETS)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Couldn't read skills:[/] {exc}")
        return SlashResult()
    if not summaries:
        ctx.console.print("[dim]No skills loaded.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Skill")
    table.add_column("Tools")
    table.add_column("Summary")
    for name in sorted(summaries):
        table.add_row(name, str(len(members.get(name, ()))), summaries[name])
    ctx.console.print(table)
    return SlashResult()


# ── Registry ─────────────────────────────────────────────────────────


def _peek(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Peek into the in-flight turn — elapsed, tool calls, and whether it
    looks healthy, stuck, or caught in a loop. Read-only and turn-safe:
    it reads a snapshot the agent loop publishes, never touches the loop."""
    tui = ctx.tui
    if tui is None or not tui._turn_running.is_set():
        ctx.console.print("[dim]No turn is running.[/]")
        return SlashResult()
    from jaeger_os.main import _pipeline
    p = _pipeline.get("turn_progress") or {}
    if not p:
        ctx.console.print(
            "[cyan]turn running[/] — still thinking; no tool calls yet.")
        return SlashResult()

    elapsed = p.get("elapsed_s", 0.0)
    calls = p.get("tool_calls", 0)
    repeated = p.get("repeated_max", 0)
    failures = p.get("failures", 0)
    last = p.get("last_tool", "")
    phase = p.get("phase", "")

    lines = [f"[bold cyan]turn running[/] — {elapsed:.0f}s · "
             f"{calls} tool call{'' if calls == 1 else 's'}"]
    if last:
        state = "running now" if phase == "start" else "returned"
        lines.append(f"  current: [bold]{last}[/] ({state})")
    if repeated >= 3:
        rt = p.get("repeated_tool") or "a tool"
        lines.append(f"  [yellow]⚠ possible loop[/] — [bold]{rt}[/] called "
                     f"{repeated}× with identical arguments")
    if failures:
        lines.append(f"  [yellow]{failures} tool failure(s)[/] so far")
    if repeated < 3 and not failures:
        lines.append("  [green]✓ looks healthy[/] — making progress")
    lines.append("  [dim](^C stops the turn · /busy changes what Enter "
                 "does mid-turn)[/]")
    ctx.console.print("\n".join(lines))
    return SlashResult()


REGISTRY: tuple[SlashCommand, ...] = (
    SlashCommand("help",      "show this command list", _help),
    SlashCommand("tools",     "list available agent tools by category", _tools),
    SlashCommand("skills",    "list the skills currently loaded", _skills),
    SlashCommand("facts",     "list stored facts (memory)", _facts),
    SlashCommand("instance",  "show active instance; `/instance <name>` to hot-switch", _instance),
    SlashCommand("instances", "list every available instance", _instances),
    SlashCommand("model",     "show active model", _model),
    SlashCommand("models",    "list every model — registry, local GGUF, LM Studio, Ollama, cloud", _models),
    SlashCommand("download",  "`/download <name>` — fetch a model from HF Hub", _download),
    SlashCommand("runtime",   "list local inference engines (llama.cpp, MLX, Ollama, LM Studio)", _runtime),
    SlashCommand("plugins",   "list bundled plugins with setup status", _plugins),
    SlashCommand("goal",      "show/set/clear an autonomous completion condition (Claude-Code-style)", _goal),
    SlashCommand("deepthink", "autonomous skill-development mode: add/list/approve/start", _deepthink),
    SlashCommand("board",     "kanban task board: show/add/approve/done/move", _board),
    SlashCommand("voice",     "show/change voice settings (mic, wake word, follow-up, barge-in)", _voice),
    SlashCommand("status",    "show session info — model, instance, uptime, context, mic", _status),
    SlashCommand("peek",      "peek into the running turn — healthy, stuck, or looping?", _peek),
    SlashCommand("statusbar", "toggle the bottom status bar", _statusbar),
    SlashCommand("quiet",     "hide voice-activity prints — `/quiet on│off`", _quiet),
    SlashCommand("busy",      "set what Enter does mid-turn: interrupt│queue│steer", _busy),
    SlashCommand("steer",     "`/steer <msg>` — steer the running turn (or run it now)", _steer),
    SlashCommand("usage",     "session usage — turns, timing, context estimate", _usage),
    SlashCommand("config",    "show the booted instance's configuration", _config),
    SlashCommand("verbose",   "toggle the ┊ tool-activity lines on/off", _verbose),
    SlashCommand("new",       "start a fresh session — clear the conversation", _new),
    SlashCommand("history",   "show the recent conversation history inline", _history),
    SlashCommand("copy",      "copy the agent's last reply to the clipboard", _copy),
    SlashCommand("undo",      "drop the last user→assistant exchange", _undo),
    SlashCommand("retry",     "re-run the last user message", _retry),
    SlashCommand("stop",      "stop all running background processes", _stop),
    SlashCommand("save",      "save the current conversation to a file", _save),
    SlashCommand("reboot",    "tear down + re-boot the pipeline (reload model/skills/config)", _reboot),
    SlashCommand("shutdown",  "shut the Jaeger down cleanly", _shutdown),
    SlashCommand("factoryreset", "erase the instance → next launch runs first-time setup", _factoryreset),
    SlashCommand("reset",     "alias for /new — clear the conversation", _reset),
    SlashCommand("quit",      "exit the TUI", _quit),
)
_BY_NAME: dict[str, SlashCommand] = {c.name: c for c in REGISTRY}


def is_slash(line: str) -> bool:
    return line.strip().startswith("/")


def dispatch(line: str, ctx: SlashContext) -> SlashResult:
    """Run a slash command. Unknown commands print a hint and return a
    no-op SlashResult (REPL continues). Args (everything after the
    command name) are forwarded to the handler as a single string."""
    parts = line.strip().lstrip("/").split(None, 1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    cmd = _BY_NAME.get(name)
    if cmd is None:
        ctx.console.print(
            f"[yellow]Unknown slash command:[/] /{name}.  Try [bold]/help[/]."
        )
        return SlashResult()
    return cmd.handler(ctx, args)
