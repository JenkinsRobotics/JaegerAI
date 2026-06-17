"""First-boot setup — the Jaeger onboarding wizard.

Triggered by main.py when the resolved instance dir has no valid
identity/config/manifest trio yet. It walks the user through setup one
step at a time — identity, model, permissions, warm-up — then writes
the three files, lays out the directory, and git-inits the instance so
skill changes are versioned. When it finishes, the system is ready to
run; boot continues straight into the agent.

Re-runnable: if the instance already exists, it is backed up aside
(`<dir>.bak.<timestamp>`) before a fresh one is built — re-running
never destroys prior work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from jaeger_os.core.instance.instance import (
    InstanceLayout,
    backup_instance_dir,
    default_instance_name,
    resolve_instance_dir,
)
from jaeger_os.core.instance.personas import (
    Persona,
    list_personas,
)
from jaeger_os.core.models.model_resolver import DEFAULT_MODEL, MODEL_REGISTRY
from jaeger_os.core.instance.schemas import (
    SCHEMA_VERSION,
    Config,
    DisplayConfig,
    DistributionConfig,
    Identity,
    InteractionConfig,
    Manifest,
    ModelConfig,
    PermissionsConfig,
    RetentionConfig,
    SkillsConfig,
    WarmupConfig,
    dump_json,
    dump_yaml,
)

_TOTAL_STEPS = 6

# Mirrors ``Identity.role``'s ``max_length=256`` in schemas.py. If
# the schema changes, this string lives next to the prompt so the
# user-facing hint follows along.
_ROLE_MAX_LEN = 256

# Kokoro voices offered at setup — (voice_id, human label).
_VOICES = [
    ("am_michael", "Michael — male, even-keeled"),
    ("af_heart", "Heart — female, warm"),
    ("am_adam", "Adam — male, bright"),
    ("af_bella", "Bella — female, expressive"),
]


# ── prompt helpers ───────────────────────────────────────────────────


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"  {label}{suffix}: ").strip() or default


def _ask_yn(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {label} ({hint}): ").strip().lower()
    return default if not raw else raw[0] == "y"


def _ask_int(label: str, default: int) -> int:
    while True:
        raw = _ask(label, str(default))
        try:
            return int(raw)
        except ValueError:
            print(f"     (expected a number, got {raw!r})")


def _ask_choice(prompt: str, options: list[tuple[str, str]], default: int = 0) -> str:
    """Numbered single-choice pick. ``options`` = [(value, label), …].
    Returns the chosen value. A bare Enter takes the default."""
    for i, (_value, label) in enumerate(options):
        marker = "›" if i == default else " "
        print(f"     {marker} {i + 1}. {label}")
    while True:
        raw = input(f"  {prompt} [{default + 1}]: ").strip()
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"     (pick 1-{len(options)})")


def _pick_persona() -> Persona | None:
    """Offer the operator a starter persona before Step 1.

    Personas are wizard-time templates only (see
    ``jaeger_os/personas/README.md``).  A picked persona supplies
    DEFAULTS for the identity questions; the operator can still type
    over any of them, so picking one never traps you into a shape.

    Returns the chosen ``Persona`` or ``None`` if the operator
    declined / no personas are installed.  Never raises — a broken
    persona file is skipped by ``list_personas`` upstream.
    """
    available = list_personas()
    if not available:
        return None
    print()
    print("  Start from a persona template?  Optional — the picked")
    print("  values become defaults for the next step; you can still")
    print("  edit any of them.  (Character levels + skill bundles")
    print("  come later on the Lilith-AI line.)")
    options: list[tuple[str, str]] = [("none", "Skip — define identity manually")]
    for p in available:
        # Keep the label tight so the wizard's choice list stays on
        # one line per option.
        label = f"{p.name} — {p.description}"
        if len(label) > 80:
            label = label[:77] + "…"
        options.append((p.id, label))
    chosen = _ask_choice("Persona", options, default=0)
    if chosen == "none":
        return None
    for p in available:
        if p.id == chosen:
            print(f"  ✓ prefilling from persona: {p.name}")
            return p
    return None


def _initialise_soul_md(
    root: Path,
    agent_name: str,
    *,
    persona_soul: str | None,
    role_overflow: str | None,
) -> None:
    """Write the initial ``soul.md`` from whatever sources the wizard
    has — persona template + role-overflow text, in that order.

    Both sources are optional and independent:

      * If a persona was picked AND its YAML has ``soul_md``, write
        that as the body.
      * If the operator's role overflowed the 256-char identity cap,
        append the full text under a "Role (full text from setup)"
        heading so context isn't lost.
      * If neither, leave ``soul.md`` absent — the agent's
        ``update_soul`` tool can create it later.

    The combined behaviour is intentionally simple: persona soul +
    overflow append cleanly without either clobbering the other.
    """
    if not persona_soul and not role_overflow:
        return
    soul_path = root / "soul.md"
    body = _SOUL_OVERFLOW_HEADER
    if persona_soul:
        body += persona_soul.strip() + "\n"
    if role_overflow:
        if persona_soul:
            body += "\n"
        body += (
            f"# {agent_name}\n\n"
            "## Role (full text from setup)\n\n"
            + role_overflow.strip()
            + "\n"
        )
    try:
        soul_path.write_text(body, encoding="utf-8")
    except OSError as exc:
        print(f"     ⚠  couldn't write soul.md ({exc}); identity.yaml "
              "is still valid")


def _banner(line: str) -> None:
    print()
    print("  ┌" + "─" * 56 + "┐")
    print(f"  │  {line:<54}│")
    print("  └" + "─" * 56 + "┘")


def _step(n: int, title: str) -> None:
    print()
    print(f"  ── Step {n}/{_TOTAL_STEPS} · {title} " + "─" * (34 - len(title)))


def _truncate_role(role_raw: str) -> tuple[str, str | None]:
    """Split a too-long role into ``(role, overflow_text)``.

    Returns the role string (≤ ``_ROLE_MAX_LEN`` chars; first sentence
    if the input was long) and the full original text when truncation
    happened — caller writes that to ``soul.md`` so nothing the user
    typed is lost.

    Returns ``(role_raw, None)`` when no truncation was needed.
    """
    role_raw = (role_raw or "").strip()
    if len(role_raw) <= _ROLE_MAX_LEN:
        return role_raw, None

    # Prefer cutting at the first sentence boundary inside the cap.
    # Falls back to a hard cut at the cap + ellipsis.
    cap = _ROLE_MAX_LEN
    window = role_raw[:cap]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut > 32:  # don't cut absurdly short
        role = role_raw[: cut + 1].strip()
    else:
        role = (role_raw[: cap - 1].rstrip() + "…")[:cap]
    return role, role_raw


# ── model pick helper (Step 2a / 2b) ─────────────────────────────────


def _wizard_pick_model(
    *,
    role_label: str,
    rec_entry,
    discovered: list,
    by_key: dict,
    allow_same_as_awake: bool,
    awake_choice: str | None,
):
    """One model-pick block, used twice (awake then asleep).

    Returns the operator's choice — a registry key, an absolute GGUF
    path, or (when ``allow_same_as_awake`` and the operator picks
    that) the literal ``awake_choice`` value passed in.

    Why this exists: pre-0.2.6 the wizard had one combined prompt
    that picked awake and implicitly hard-coded asleep to the tier
    recommendation. Operators couldn't override the asleep model
    without hand-editing config.yaml, and couldn't see that the
    recommended file was already on disk in LM Studio etc. Both
    failures share the same UI — surface the recommendation,
    discovery state, registry, custom path — so they share this
    helper.
    """
    from jaeger_os.core.models.model_resolver import (
        DEFAULT_MODEL, MODEL_REGISTRY,
    )
    print(f"  ── {role_label} ──")
    print(f"    Recommended: {rec_entry.display_name}  "
          f"({rec_entry.size_gb:.1f} GB, score {rec_entry.score_pct:.1f}%, "
          f"{rec_entry.tokens_per_task} tok/task)")
    print(f"    {rec_entry.notes}")

    found = by_key.get(rec_entry.registry_key)
    if found is not None:
        rec_annot = f" — ✓ found locally ({found.source})"
    else:
        rec_annot = f" — will download ~{rec_entry.size_gb:.1f} GB on first use"

    print()
    opts: list[tuple[str, str]] = [
        ("__recommended__",
         f"Use recommended ({rec_entry.display_name}){rec_annot}"),
        ("__registry__", "Choose from the full registry"),
    ]
    if discovered:
        opts.append(("__discovered__",
                     f"Pick from {len(discovered)} discovered GGUF file(s) "
                     f"on this machine"))
    opts.append(("__custom__", "Provide a custom GGUF path"))
    if allow_same_as_awake and awake_choice:
        opts.append(("__same_as_awake__",
                     f"Same as awake ({awake_choice}) — no swap, saves memory"))

    mode = _ask_choice("Pick", opts, default=0)

    if mode == "__recommended__":
        chosen = rec_entry.registry_key
        if found is not None:
            print(f"     → {chosen} (using local {found.source} copy)")
        else:
            print(f"     → {chosen} (will download on first use)")
        return chosen

    if mode == "__registry__":
        # Sort registry keys; mark DEFAULT_MODEL with "(default)".
        reg_opts = [
            (key, f"{key}" + ("  (default)" if key == DEFAULT_MODEL else ""))
            for key in MODEL_REGISTRY
        ]
        default_idx = next((i for i, (k, _) in enumerate(reg_opts)
                            if k == DEFAULT_MODEL), 0)
        chosen = _ask_choice("Registry key", reg_opts, default=default_idx)
        local = by_key.get(chosen)
        if local is not None:
            print(f"     → {chosen} (using local {local.source} copy)")
        else:
            print(f"     → {chosen} (will download on first use)")
        return chosen

    if mode == "__discovered__":
        disc_opts = [
            (str(d.path),
             f"{d.filename}  ({d.size_gb:.1f} GB)  — {d.source}")
            for d in discovered
        ]
        chosen = _ask_choice("Pick a discovered file", disc_opts, default=0)
        print(f"     → {chosen}")
        return chosen

    if mode == "__same_as_awake__":
        print(f"     → same as awake ({awake_choice}) — deep-think swap "
              "disabled")
        return awake_choice

    # Custom path
    chosen = _ask("Path to a .gguf file", "")
    if chosen and not Path(chosen).expanduser().exists():
        print(f"     ⚠  {chosen} not found — saving anyway; "
              "resolve it before first use.")
    return chosen


# ── the wizard ───────────────────────────────────────────────────────


def run_wizard(
    *,
    force: bool = False,
    instance_name: str | None = None,
    boot_after: bool = True,
) -> InstanceLayout:
    """Walk first-boot setup end to end. Returns the new instance layout.

    ``boot_after`` controls the final "Booting now…" message. The
    auto-fire-on-first-launch callers in ``main.py`` keep the default
    ``True`` because the agent does in fact boot after the wizard
    returns. The explicit ``./run.sh setup`` subcommand passes
    ``False`` — its caller exits cleanly after the wizard and there
    is no boot, so claiming "Booting now…" would be a lie.
    """
    from jaeger_os.core.instance.instance import operator_state_root
    # One name, not two: when no instance name is given (the common
    # ``jaeger setup`` path), the agent's name from Step 1 names its folder.
    # Defer the layout until we have that name. An explicit name (dev /
    # ``--instance``) resolves up front as before.
    name = instance_name
    layout = InstanceLayout(root=resolve_instance_dir(name)) if name else None

    _banner("Welcome to Jaeger-OS")
    print()
    # Show the install destination LOUDLY before anything else — the path was
    # set by the install, never asked here. An operator who didn't mean to
    # land in this install (e.g. inside the sandbox shell) can bail now.
    if layout is not None:
        print("  This agent will live at:")
        print(f"    {layout.root}/")
    else:
        print("  This agent will live under:")
        print(f"    {operator_state_root() / 'instances'}/")
        print("  …in a folder named from the agent's name (you'll set it in Step 1).")
    print()
    print("  Install location set by the install — to put an agent")
    print("  somewhere else, cancel (Ctrl-C), re-install with a")
    print("  different JAEGER_HOME, and re-run.")
    print()
    print("  Six quick steps:")
    print("    1. identity        4. interaction")
    print("    2. model           5. warm-up")
    print("    3. permissions     6. review")
    print()
    print("  Tip: prompts show a [default] in brackets — press Enter to accept.")

    if layout is not None and layout.exists():
        if not force and not _ask_yn(
            "\n  This instance already exists. Back it up and start fresh?", False
        ):
            print("  Setup cancelled.")
            sys.exit(0)
        backup_instance_dir(layout)

    # ── Optional · Persona prefill (0.3.0 framework) ───────────────
    # Personas are wizard-time templates only — they prefill the
    # Step 1 defaults so an operator who's happy with a canonical
    # shape can press Enter through identity instead of typing it
    # out.  Zero runtime impact: after the wizard finishes, the
    # instance directory just has the resulting identity.yaml +
    # soul.md.  The full character-level / skill-bundle / tool-gate
    # system is deferred to the Lilith-AI line — see
    # ``jaeger_os/personas/README.md``.
    persona = _pick_persona()
    p_id = persona.identity if persona else None

    # ── Step 1 · Identity ───────────────────────────────────────────
    _step(1, "Identity")
    print("  Who is this Jaeger? Their name also names the instance folder.")
    agent_name = _ask(
        "Agent display name",
        p_id.display_name if p_id else "Jarvis",
    )
    # WIZ-2: surface the role length cap AND split a too-long role
    # gracefully — first sentence goes into identity.role, the full
    # text into soul.md. Previously a long answer crashed the wizard
    # with a pydantic ValidationError.
    #
    # Length hint uses parentheses, not brackets, so it doesn't
    # collide visually with the `[default]` suffix _ask appends.
    # Without that, the prompt read as
    # ``Role … [≤256 chars] [general-purpose agentic assistant]:``
    # which looks like two unrelated hints rather than "max-len,
    # then default."
    role_raw = _ask(
        f"Role — what does it do?  (≤{_ROLE_MAX_LEN} chars)",
        p_id.role if p_id else "general-purpose agentic assistant",
    )
    role, role_overflow = _truncate_role(role_raw)

    # Unified name: derive the instance folder from the agent's name when one
    # wasn't given explicitly. Slug → a clean folder name; a collision triggers
    # the same back-up prompt as an explicit name.
    if layout is None:
        import re as _re
        name = (_re.sub(r"[^a-z0-9_-]+", "-", agent_name.strip().lower())
                .strip("-_") or "agent")
        layout = InstanceLayout(root=resolve_instance_dir(name))
        print()
        print(f"  → this agent's folder: {layout.root}/")
        if layout.exists():
            if not force and not _ask_yn(
                "    A folder with that name exists. Back it up and start fresh?",
                False,
            ):
                print("  Setup cancelled.")
                sys.exit(0)
            backup_instance_dir(layout)
    if role_overflow:
        print(f"     (role > {_ROLE_MAX_LEN} chars — saved full text to "
              f"soul.md; identity.role uses the first sentence.)")
    personality = _ask(
        "Personality (one line)",
        p_id.personality if p_id
        else "Helpful, capable, concise — honest about uncertainty.",
    )
    print("  Voice:")
    # If the persona pinned a voice_id and it matches one of our
    # offered Kokoro voices, surface it as the default — operator
    # can still override.  Unknown / missing voice_id falls through
    # to the existing default-0 behaviour.
    voice_default_idx = 0
    if p_id and p_id.voice_id:
        for i, (vid, _label) in enumerate(_VOICES):
            if vid == p_id.voice_id:
                voice_default_idx = i
                break
    voice_id = _ask_choice("Pick a voice", _VOICES, default=voice_default_idx)
    identity = Identity(
        name=agent_name, role=role,
        personality=personality,
        voice_tone=(p_id.voice_tone if p_id else "clear, even-keeled"),
        voice_id=voice_id,
    )

    # ── Step 2 · Model ──────────────────────────────────────────────
    _step(2, "Model")
    # Detect the host's unified-memory tier so we can recommend a
    # data-validated awake / asleep pair, then scan the filesystem so
    # an operator who already has the recommended GGUFs (LM Studio,
    # HF cache, ~/.jaeger/models, …) doesn't get re-prompted to
    # download 15+ GB.
    from jaeger_os.core.models.host_recommendation import (
        detect_total_memory_gb, classify_tier, recommend_for_tier,
    )
    from jaeger_os.core.models.local_discovery import (
        discover_local_gguf_files, match_to_registry,
    )
    from jaeger_os.core.models.model_resolver import (
        ensure_symlink_in_repo_models,
    )
    detected_gb = detect_total_memory_gb()
    detected_tier = classify_tier(detected_gb)
    rec = recommend_for_tier(detected_tier)
    print(f"  Host: {detected_gb:.1f} GB unified memory → "
          f"{rec.tier_label} tier")
    print(f"  {rec.description}")
    print()

    # Step 2a — discover existing GGUFs so we can annotate the prompts
    print("  Scanning for GGUF models on this machine…")
    discovered = discover_local_gguf_files()
    by_key = match_to_registry(discovered)
    if discovered:
        print(f"  Found {len(discovered)} GGUF file(s):")
        for d in discovered:
            size = f"{d.size_gb:.1f} GB" if d.size_gb >= 0 else "size?"
            print(f"    • {d.filename}  ({size})  — {d.source}")
    else:
        print("  (none found — registry picks will download from "
              "Hugging Face on first use)")
    print()

    model_path = _wizard_pick_model(
        role_label="Awake model (real-time conversation)",
        rec_entry=rec.awake,
        discovered=discovered,
        by_key=by_key,
        allow_same_as_awake=False,
        awake_choice=None,
    )
    # Auto-symlink: if the recommended awake model is already on disk
    # somewhere we know about, drop a symlink into the in-repo models
    # dir so the resolver finds it without a Hugging Face round-trip.
    if model_path == rec.awake.registry_key and rec.awake.registry_key in by_key:
        linked = ensure_symlink_in_repo_models(
            by_key[rec.awake.registry_key].path,
            registry_key=rec.awake.registry_key,
        )
        if linked is not None:
            print(f"     ✓ linked {linked.name} (no download needed)")

    print()
    asleep_path = _wizard_pick_model(
        role_label="Asleep model (deep-think / kanban work)",
        rec_entry=rec.asleep,
        discovered=discovered,
        by_key=by_key,
        allow_same_as_awake=(rec.awake.registry_key
                             != rec.asleep.registry_key),
        awake_choice=model_path,
    )
    if (asleep_path == rec.asleep.registry_key
            and rec.asleep.registry_key in by_key
            and asleep_path != model_path):
        linked = ensure_symlink_in_repo_models(
            by_key[rec.asleep.registry_key].path,
            registry_key=rec.asleep.registry_key,
        )
        if linked is not None:
            print(f"     ✓ linked {linked.name} (no download needed)")

    # ── Step 3 · Permissions ────────────────────────────────────────
    _step(3, "Permissions")
    print("  Some tools act on the world — run code, control the computer,")
    print("  install packages. How should the agent handle those?")
    perm_mode = _ask_choice(
        "Choose",
        [
            ("confirm", "Ask me before each action  (recommended)"),
            ("allow", "Auto-allow everything  (trusted, unattended robot)"),
        ],
        default=0,
    )

    # ── Step 4 · Interaction (WIZ-3) ────────────────────────────────
    # How does the user want to talk to {name} by default? The choice
    # lands in config.yaml so launchers (the tray's "Open" action,
    # `jaeger` no-arg behaviour later) pick the right surface
    # without re-asking. Voice is experimental in 0.2.0 — the
    # ``speexdsp`` AEC dep isn't packaged yet; without it the
    # always-on mic picks up nearby podcast audio.
    _step(4, "Interaction")
    print(f"  How do you want to talk to {agent_name} by default?")
    interaction_mode = _ask_choice(
        "Pick a mode",
        [
            ("tui", "Type — terminal TUI is my default surface  (recommended)"),
            ("gui", "Floating window — PyQt6 chat bubble"),
            ("voice", "Voice — always-on mic + spoken responses  (experimental)"),
        ],
        default=0,
    )
    voice_enable_choice = False
    if interaction_mode == "voice":
        print()
        print("     ⚠  voice is experimental.")
        # VOICE-2: probe for speexdsp (acoustic echo cancellation).
        # AEC keeps the always-on mic from feeding back podcast / YouTube
        # audio playing nearby.  Two paths exist in 0.3.0:
        #
        #   • macOS + ``--audio-backend avaudio`` (default): AVAudioEngine's
        #     built-in voice-processing AEC + NS + AGC kicks in
        #     automatically when no speexdsp is wired (see
        #     ``whisper_stt/_base.py``), so speexdsp is OPTIONAL on Mac.
        #   • Anywhere else (Linux + portaudio, macOS + ``--audio-backend
        #     portaudio``): speexdsp is the only AEC available; without
        #     it, mic-pause-during-TTS is the only echo defence.
        #
        # We still offer one-tap install if missing because (a) it's the
        # only cross-platform AEC and (b) the operator may want to fall
        # back to portaudio later without breaking AEC.
        if _has_speexdsp():
            print("        speexdsp detected — echo cancellation will work "
                  "on every backend.")
        else:
            print("        speexdsp NOT installed.  On macOS with the")
            print("        default AVAudio backend, Apple's voice-processing")
            print("        AEC will kick in automatically.  On other")
            print("        platforms (or ``--audio-backend portaudio``)")
            print("        background audio will leak into the mic.")
            print("            pip install speexdsp")
            if _ask_yn("        Try the install now?", False):
                _install_speexdsp()
        voice_enable_choice = _ask_yn(
            "  Enable always-on voice now (you can flip in config.yaml later)?",
            False,
        )
    elif interaction_mode == "gui":
        print()
        print("     ⚠  the PyQt6 GUI is planned for a future release;")
        print("        for now `jaeger` will fall back to the TUI when invoked.")

    # ── Step 5 · Warm-up ────────────────────────────────────────────
    # Vision (Moondream2) is wired in code (core/tools/vision.py) but
    # has no test coverage and no bench case in 0.2.x — surfacing it
    # in the wizard implied a first-class feature it isn't yet. The
    # warmup flag is hard-coded off here; anyone who needs it can set
    # ``warmup.vision: true`` in config.yaml. Returns to the wizard
    # when 0.3.0 lands proper vision validation.
    _step(5, "Warm-up")
    print("  Every system (TTS, STT, …) warms at startup so it's instant on")
    print("  first use — no per-node toggle (warming a node never opens the")
    print("  mic; voice MODE stays the separate choice above). When setup")
    print("  finishes it will download + warm + verify all systems, so")
    print("  \"ready\" means all systems go. Vision (heavy VLM) stays opt-in.")
    warm_tts = True
    warm_stt = True
    warm_vision = False

    # Subprocess HOME isolation (was a Step 6 in 0.2.5) is a power-user
    # feature — runs the agent's spawned subprocesses with a private
    # HOME so git/ssh/npm don't see the operator's real identity. ~95%
    # of operators want the default (inherit), and the prompt confused
    # the rest. Removed from the wizard; opt in via config.yaml's
    # ``subprocess.use_instance_home`` field. The populate_instance_home
    # code stays untouched for anyone who flips that bit by hand.
    use_instance_home = False
    git_name: str | None = None
    git_email: str | None = None
    ssh_key_source: str | None = None

    # ── Step 6 · Review ─────────────────────────────────────────────
    _step(6, "Review")
    print(f"     Identity     {agent_name} — {role}")
    print(f"     Personality  {personality}")
    print(f"     Voice        {voice_id}")
    print(f"     Awake model  {model_path}")
    if asleep_path == model_path:
        print(f"     Asleep model (same as awake — no swap)")
    else:
        print(f"     Asleep model {asleep_path}  (swaps in during deep-think)")
    print(f"     Permissions  {'ask before each action' if perm_mode == 'confirm' else 'auto-allow'}")
    print(f"     Interaction  default mode = {interaction_mode}")
    print(f"     Warm-up      TTS={'on' if warm_tts else 'off'}  "
          f"STT={'on' if warm_stt else 'off'}")
    if not _ask_yn("\n  Looks good — create the Jaeger?", True):
        print("  Setup cancelled. Re-run to start over.")
        sys.exit(0)

    # WIZ-5: ctx default raised 16384 → 32768. The 0.1.0 default plus
    # the full tool surface guaranteed a ContextOverflow on the first
    # message (tool schemas alone ate ~14K). 32K is comfortable on
    # Apple Silicon and matches what the model trained on. See
    # docs/ROADMAP_0.2.0.md → Group 2.
    from jaeger_os.core.instance.schemas import DeepThinkConfig, VoiceConfig
    config = Config(
        instance_name=name,
        model=ModelConfig(model_path=model_path, ctx=32768, gpu_layers=-1),
        display=DisplayConfig(),
        skills=SkillsConfig(),
        retention=RetentionConfig(),
        # 0.2.6: the asleep model is whatever the operator picked in
        # Step 2's asleep prompt — either the tier recommendation, a
        # different registry key, a discovered GGUF path, a custom
        # path, or the same value as ``model_path`` (when "same as
        # awake" was picked). DeepThinkConfig's default coder_model
        # is now a fallback for upgrades from older instances.
        deep_think=DeepThinkConfig(coder_model=asleep_path),
        warmup=WarmupConfig(tts=warm_tts, stt=warm_stt, vision=warm_vision),
        permissions=PermissionsConfig(mode=perm_mode),
        interaction=InteractionConfig(default_mode=interaction_mode),
        # VOICE-1/2: default OFF unless the user explicitly opted in
        # during the interaction step. Re-flippable in config.yaml or
        # via ``/voice on`` in the TUI.
        voice=VoiceConfig(enabled=voice_enable_choice),
    )
    manifest = Manifest(instance_name=name, schema_version=SCHEMA_VERSION)

    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, identity)
    dump_yaml(layout.config_path, config)
    dump_json(layout.manifest_path, manifest)
    # INST-3 (0.2.0): record install provenance per instance.
    # ``jaeger update`` rewrites ``last_updated_with_framework``;
    # ``jaeger restore`` rewrites ``install_method`` + adds
    # ``restored_from``. Idempotent — overwriting is fine.
    from jaeger_os import __version__ as _jver
    from jaeger_os.core.instance.instance import detect_install_method
    install_method = detect_install_method()
    dump_yaml(layout.distribution_path, DistributionConfig(
        created_with_framework=_jver,
        last_updated_with_framework=_jver,
        install_method=install_method,
        install_source=_install_source_for(install_method),
    ))
    # Write soul.md from the persona template (if any) AND / OR the
    # role-overflow text (if any).  Both sources are optional and
    # combine cleanly — see ``_initialise_soul_md``.  Short role +
    # no persona → soul.md stays absent, identical to the
    # pre-persona behaviour (the agent's ``update_soul`` tool can
    # write one later if it ever needs to).
    _initialise_soul_md(
        layout.root,
        agent_name,
        persona_soul=persona.soul_md if persona else None,
        role_overflow=role_overflow,
    )
    # INST-4: populate the per-instance HOME jail if the user opted
    # in. Idempotent; safe to re-run.
    if use_instance_home:
        from jaeger_os.core.instance.subprocess_env import populate_instance_home
        populate_instance_home(
            layout,
            git_name=git_name,
            git_email=git_email,
            ssh_key_source=ssh_key_source,
        )
    _git_init(layout.root)

    # WIZ-4: drop a sourceable env file at ``~/.jaeger/jaeger.env`` so
    # the user can opt into a stable ``JAEGER_INSTANCE_DIR`` without
    # memorising the path. Silent on multi-instance setups where the
    # user clearly already knows what they're doing (env var was set
    # going in).
    _write_env_file(layout.root, name)

    # Make this the default agent a bare `jaeger` runs? Default YES — you set
    # up an agent in order to run it. Writes the sticky active-instance pointer
    # so a bare `jaeger` resolves here without an --instance flag.
    if _ask_yn("\n  Make this the default agent (a bare `jaeger` runs it)?",
               True):
        from jaeger_os.core.instance.instance import write_active_instance
        write_active_instance(name)
        print(f"  ✓ a bare `jaeger` now runs {name!r}.")

    # Prepare — download + warm + verify every system, so "ready" means all
    # systems go (the operator's rule). One-time; later launches are fast
    # since weights are cached. LOUD + best-effort: failures are shown, never
    # hidden, and the operator decides whether to proceed (the instance is
    # already created, so we report rather than hard-block).
    all_go = _prepare_and_verify(name)

    if all_go:
        _banner(f"{agent_name} is ready — all systems go")
    else:
        _banner(f"{agent_name} created — some systems need attention")
    print()
    print(f"  Instance: {layout.root}")
    if not all_go:
        print("  ⚠ Some systems did not come up (see the readiness report above).")
        print("    Launch and run `diagnostics` to inspect, or re-run setup once")
        print("    the cause is fixed.")
    _print_env_hint(name)
    if boot_after:
        print("  Booting now…")
    else:
        # Explicit-subcommand path: ``./run.sh setup`` exits after the
        # wizard, no boot. Tell the operator how to launch and how to
        # re-run the wizard if they want to.
        print("  Done — instance ready to launch.")
        print()
        if name == default_instance_name():
            print("  Launch:    ./jaeger")
        else:
            print(f"  Launch:    ./jaeger --instance {name}")
        print(f"  Re-config: ./jaeger instances edit {name}")
    print()
    return layout


def _prepare_and_verify(name: str) -> bool:
    """Download + warm + verify every system for the freshly-created
    instance, so setup completes only when all systems are go (the
    operator's rule). Boots the instance once (loads the model + warms
    TTS/STT/vision/… via ``warm_plugins`` → the readiness registry, which
    prints the loud per-system summary), reads the readiness report, then
    tears the boot down. Returns True when no applicable system is offline.

    Best-effort: any error here is reported but never fatal — the instance
    is already written, so we'd rather say "some systems need attention"
    than crash setup."""
    # Escape hatch: tests + CI (and operators who want a fast, verify-later
    # setup) skip the heavy verify boot. Real setup runs it.
    import os
    if os.environ.get("JAEGER_SKIP_PREPARE"):
        print("  (JAEGER_SKIP_PREPARE set — skipping the verify boot)")
        return True
    print()
    print("  Preparing systems — loading the model + downloading/warming")
    print("  voice (and vision, if enabled). One-time; later launches reuse")
    print("  the cached weights…")
    try:
        from jaeger_os.main import _pipeline, boot_for_tui
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ could not start the prepare boot: "
              f"{type(exc).__name__}: {exc}")
        return False
    boot = None
    try:
        boot = boot_for_tui(instance_name=name, warmup=True)
        report = _pipeline.get("readiness") or {}
        return bool(report.get("all_go", False))
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ prepare/verify failed: {type(exc).__name__}: {exc}")
        return False
    finally:
        if boot is not None:
            try:
                boot.cleanup()
            except Exception:  # noqa: BLE001
                pass


# ── soul.md initial-body writer (0.3.0) ──────────────────────────────


_SOUL_OVERFLOW_HEADER = (
    "<!-- soul.md — who this instance is: character, values, voice.\n"
    "     Auto-generated by the wizard (persona template and / or\n"
    "     a role longer than identity.role's 256-char cap). Edit\n"
    "     freely; loaded into the system prompt at startup. -->\n\n"
)


# Note: ``_write_soul_from_role`` (WIZ-2, 0.2.x) was retired in 0.3.0.
# Its single role-overflow case is now handled by
# ``_initialise_soul_md`` defined near the top of this module, which
# also handles the optional persona-template prefill in one place.


# ── speexdsp probe + install (VOICE-2) ───────────────────────────────


def _has_speexdsp() -> bool:
    """Best-effort detection: importable means the AEC backend will
    load when the voice loop spins up. ``find_spec`` avoids actually
    importing speexdsp (which can be slow and side-effecty)."""
    try:
        import importlib.util
        return importlib.util.find_spec("speexdsp") is not None
    except Exception:  # noqa: BLE001
        return False


def _install_speexdsp() -> bool:
    """One-shot ``pip install speexdsp`` driven from the wizard.

    Returns True on a clean install. The wizard prints either way —
    the user already opted in via the y/n prompt — and we don't fail
    the wizard if the install errors (mic still works without AEC,
    just with background-audio feedthrough).
    """
    import subprocess
    print("     installing speexdsp via pip…", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "speexdsp"],
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"     ⚠  install failed ({exc}); the mic will work without AEC.")
        return False
    if result.returncode != 0:
        print(f"     ⚠  pip returned {result.returncode}; "
              "install speexdsp manually if you need AEC.")
        return False
    print("     speexdsp installed.")
    return True


# ── distribution provenance (INST-3) ─────────────────────────────────


def _install_source_for(install_method: str) -> str | None:
    """Best-effort install source for the distribution manifest.

    Pip and pipx don't expose the original index URL cleanly at
    runtime; we record a sensible label per method instead. The
    field is informational — it's what shows up in ``jaeger
    instance inspect`` and bug-report dumps, not a programmatic
    contract.
    """
    if install_method == "pipx":
        return "pipx"
    if install_method == "pip":
        return "PyPI (pip)"
    if install_method == "dev-checkout":
        return f"dev checkout @ {Path(__file__).resolve().parent.parent.parent.parent}"
    return None


# ── env file (WIZ-4) ─────────────────────────────────────────────────


_ENV_FILE_HEADER = (
    "# Auto-generated by the Jaeger wizard. Source this in your shell\n"
    "# (or your shell's rc file) to point every `jaeger` invocation at\n"
    "# the instance the wizard just created — no more silent fallback\n"
    "# to the bundled placeholder. Safe to re-source; safe to delete.\n"
    "#\n"
    "#   source ~/.jaeger/jaeger.env\n"
    "#\n"
)


def _env_file_path() -> Path:
    """The ``jaeger.env`` location — sits alongside the rest of the
    operator state at ``<install_root>/.jaeger_os/jaeger.env``."""
    from jaeger_os.core.instance.instance import operator_state_root
    return operator_state_root() / "jaeger.env"


def _write_env_file(instance_root: Path, instance_name: str) -> None:
    """Persist ``export JAEGER_INSTANCE_DIR=…`` (+ INSTANCE_NAME) at
    ``<install_root>/.jaeger_os/jaeger.env`` so the user has a single,
    predictable file to ``source``. Best-effort — failures print a
    note and let the wizard finish (the instance is already on disk).
    """
    env_path = _env_file_path()
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        body = (
            _ENV_FILE_HEADER
            + f'export JAEGER_INSTANCE_DIR="{instance_root}"\n'
            + f'export JAEGER_INSTANCE_NAME="{instance_name}"\n'
        )
        env_path.write_text(body, encoding="utf-8")
        env_path.chmod(0o600)
    except OSError as exc:
        print(f"     ⚠  couldn't write {env_path} ({exc}); "
              f"set JAEGER_INSTANCE_DIR={instance_root} manually.",
              flush=True)


def _print_env_hint(instance_name: str) -> None:
    """One-liner the user can copy verbatim into their shell rc."""
    env_path = _env_file_path()
    print(f"  Env file: {env_path}")
    # Print the source line in a way that's obvious to copy.
    print("  Add this to your shell rc (zsh/bash) to make it stick:")
    print(f'    source "{env_path}"')


# ── git ──────────────────────────────────────────────────────────────


def _git_init(root: Path) -> None:
    if not _has_git():
        return
    try:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True, capture_output=True, timeout=10,
        )
        (root / ".gitignore").write_text(
            "# Auto-generated by the Jaeger wizard.\n"
            ".lock\n"
            "credentials/\n"
            "logs/\n"
            "memory/episodic.embeddings.npz\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=jaeger@local",
             "-c", "user.name=jaeger-setup",
             "commit", "-q", "-m", "jaeger: initial instance"],
            check=False, capture_output=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[jaeger] git init skipped: {exc}", file=sys.stderr, flush=True)


def _has_git() -> bool:
    try:
        from shutil import which
        return which("git") is not None
    except Exception:  # noqa: BLE001
        return False
