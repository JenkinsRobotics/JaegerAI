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

import os
import subprocess
import sys
from pathlib import Path

from jaeger_ai.core.instance.instance import (
    InstanceLayout,
    backup_instance_dir,
    default_instance_name,
    resolve_instance_dir,
)
from jaeger_ai.core.instance.schemas import (
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


# Every prompt below funnels through ``_read_line`` so the wizard has ONE
# answer to "there is no human here". Two distinct cases:
#
#   • ``JAEGER_NONINTERACTIVE=1`` — an explicit contract for callers that
#     spawn setup with no operator attached (the Swift app / ARES bridge
#     drive ``create_instance`` directly today, but the guided flow must
#     not hard-crash if anything ever reaches for it).
#   • stdin runs out mid-walk (Ctrl-D, a piped heredoc that ended). The
#     first EOF latches ``_STDIN_EXHAUSTED`` so the REMAINING prompts take
#     their defaults silently instead of raising EOFError per question.
#
# Deliberately NOT keyed on ``sys.stdin.isatty()``: the wizard's own tests
# drive it with a monkeypatched ``builtins.input`` and no tty, and treating
# that as non-interactive would skip the canned answers.
_NONINTERACTIVE_ENV = "JAEGER_NONINTERACTIVE"
_STDIN_EXHAUSTED = False


def _noninteractive() -> bool:
    """True when the caller declared that nobody can answer a prompt."""
    raw = os.environ.get(_NONINTERACTIVE_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _no_answer_available() -> bool:
    """True when further prompting cannot produce an operator answer."""
    return _noninteractive() or _STDIN_EXHAUSTED


def _read_line(prompt: str) -> str | None:
    """One raw prompt. ``None`` means "no answer available" — never raises.

    Ctrl-C exits cleanly rather than dumping a traceback over a
    half-finished setup walk.
    """
    global _STDIN_EXHAUSTED
    if _no_answer_available():
        return None
    try:
        return input(prompt)
    except EOFError:
        _STDIN_EXHAUSTED = True
        print()
        return None
    except KeyboardInterrupt:
        print("\n  Setup cancelled.")
        sys.exit(1)


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = _read_line(f"  {label}{suffix}: ")
    if raw is None:
        return default
    return raw.strip() or default


def _ask_yn(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = _read_line(f"  {label} ({hint}): ")
    if raw is None:
        return default
    raw = raw.strip().lower()
    return default if not raw else raw[0] == "y"


def _ask_int(label: str, default: int) -> int:
    while True:
        raw = _ask(label, str(default))
        try:
            return int(raw)
        except ValueError:
            if _no_answer_available():
                return default
            print(f"     (expected a number, got {raw!r})")


def _ask_choice(prompt: str, options: list[tuple[str, str]], default: int = 0) -> str:
    """Numbered single-choice pick. ``options`` = [(value, label), …].
    Returns the chosen value. A bare Enter takes the default."""
    for i, (_value, label) in enumerate(options):
        marker = "›" if i == default else " "
        print(f"     {marker} {i + 1}. {label}")
    while True:
        raw = _read_line(f"  {prompt} [{default + 1}]: ")
        if raw is None:
            return options[default][0]
        raw = raw.strip()
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"     (pick 1-{len(options)})")


def _pick_character():
    """Pick the CHARACTER this instance plays — characters ARE the persona
    now (jaeger_os/personality/characters/).  Returns ``(id, shim)`` where the
    shim mirrors the persona-identity fields Step 1 prefills from, so the
    instance's identity.yaml + active_character both reflect the character.
    The operator picks a character instead of authoring a prompt by hand.
    """
    rows = _character_rows()
    print()
    print("  Pick the character this Jaeger plays — its persona, name and")
    print("  voice all come from the character (edit later in Studio).")
    options = [(r[0], f"{r[1]} — {r[2]}"[:78]) for r in rows]
    default = next((i for i, r in enumerate(rows) if r[0] == "assistant"), 0)
    chosen = _ask_choice("Character", options, default=max(0, default))
    shim = _character_shim(chosen, rows=rows)
    print(f"  ✓ this Jaeger plays: {shim.display_name}")
    return chosen, shim


def _character_rows() -> list[tuple[str, str, str, str, str]]:
    """Every installed character as ``(id, name, role, voice_id,
    voice_tone)`` — the identity fields setup prefills from. Shared by
    the interactive picker and the non-interactive ``create_instance``
    (the bridge's onboarding path). A broken sheet is skipped."""
    import yaml
    from jaeger_ai.personality.character import characters_root

    raw_rows: list[tuple[str, str, str, str, str, bool]] = []
    root = characters_root()
    if not root.is_dir():
        return []
    for p in sorted(root.iterdir()):
        y = p / "character.yaml"
        if not y.exists():
            continue
        try:
            d = yaml.safe_load(y.read_text(encoding="utf-8")) or {}
            idy = d.get("identity") or {}
            is_neutral = bool(d.get("neutral", False)) or p.name == "assistant"
            raw_rows.append((p.name, d.get("name", p.name), idy.get("role", ""),
                             idy.get("voice_id", ""), idy.get("voice_tone", ""), is_neutral))
        except Exception:  # noqa: BLE001 — a broken sheet is just skipped
            continue
    raw_rows.sort(key=lambda r: (not r[5], r[1].lower()))
    return [(r[0], r[1], r[2], r[3], r[4]) for r in raw_rows]


def _character_shim(char_id: str, rows=None):
    """The identity-prefill shim for one character id. Raises
    ``LookupError`` when the id names no installed character."""
    from types import SimpleNamespace
    r = next((row for row in (rows or _character_rows())
              if row[0] == char_id), None)
    if r is None:
        raise LookupError(f"unknown character: {char_id!r}")
    return SimpleNamespace(
        display_name=r[1], role=r[2],
        personality=f"Plays the {r[1]} character.",
        voice_id=r[3], voice_tone=r[4])


def _initialise_soul_md(
    root: Path,
    agent_name: str,
    *,
    persona_soul: str | None,
    role_overflow: str | None,
) -> None:
    """Write the initial ``SOUL.md`` from whatever sources the wizard
    has — persona template + role-overflow text, in that order.

    Identity only. Operational directives (tools, mission, hardware
    bindings) belong in ``AGENTS.md`` — see
    ``jaeger_agent.prompts.context_blocks``; the wizard writes no
    directives because it does not know the deployment.

    Both sources are optional and independent:

      * If a persona was picked AND its YAML has ``soul_md``, write
        that as the body.
      * If the operator's role overflowed the 256-char identity cap,
        append the full text under a "Role (full text from setup)"
        heading so context isn't lost.
      * If neither, leave ``SOUL.md`` absent — the agent's
        ``update_soul`` tool can create it later, and the prompt simply
        carries no identity prose in the meantime (no built-in default).

    The combined behaviour is intentionally simple: persona soul +
    overflow append cleanly without either clobbering the other.
    """
    if not persona_soul and not role_overflow:
        return
    # Canonical spelling — the runtime resolves the legacy lowercase
    # ``soul.md`` too, for instances created before the split.
    soul_path = root / "SOUL.md"
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
        print(f"     ⚠  couldn't write SOUL.md ({exc}); identity.yaml "
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
    from jaeger_ai.core.models.model_resolver import (
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

    # Custom path. Re-ask on an empty answer instead of returning "":
    # create_instance substitutes the tier recommendation for a blank
    # model, so falling through silently made Review print an empty
    # "Awake model" (and, when both picks were blank, wrongly claim
    # "same as awake — no swap") for an instance that actually got two
    # different recommended models. Announce the fallback when no answer
    # can be obtained at all.
    while True:
        chosen = _ask("Path to a .gguf file", "")
        if chosen:
            break
        if _no_answer_available():
            print(f"     → no path given — using recommended "
                  f"({rec_entry.registry_key})")
            return rec_entry.registry_key
        print("     (enter a path to a .gguf file, or Ctrl-C to cancel)")
    if not Path(chosen).expanduser().exists():
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
    from jaeger_ai.core.instance.instance import operator_state_root
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

    # ── Character pick ──────────────────────────────────────────────
    # Characters ARE the persona (0.5): the pick prefills Step 1's
    # identity defaults and binds the instance to the character at the
    # end. (The 0.3 persona-template path was retired with it.)
    char_id, p_id = _pick_character()

    # ── Step 1 · Identity ───────────────────────────────────────────
    _step(1, "Identity")
    if name:
        # An explicit instance name (--name / agent create <name>) already
        # fixed the folder above — the operator contract keeps the AGENT
        # name separate from that (freely editable, never renames the
        # folder), so default to what they typed rather than re-deriving
        # a folder-naming echo.
        print("  Who is this Jaeger? (the instance folder is already set above)")
    else:
        print("  Who is this Jaeger? Their name also names the instance folder.")
    # Default order: CLI-passed name (this instance's --name pin) wins,
    # then the picked character's name, then the hard-coded "Jarvis" —
    # always editable, matching the bridge's onboarding precedence
    # (pin > character preset > … ; here "…" is just the built-in
    # placeholder since there's no separate user-edit state in a
    # single ``input()`` prompt).
    agent_name = _ask(
        "Agent display name",
        name or (p_id.display_name if p_id else "Jarvis"),
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
        name = _slug(agent_name)
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

    # ── Step 2 · Model ──────────────────────────────────────────────
    _step(2, "Model")
    # Detect the host's unified-memory tier so we can recommend a
    # data-validated awake / asleep pair, then scan the filesystem so
    # an operator who already has the recommended GGUFs (LM Studio,
    # HF cache, ~/.jaeger/models, …) doesn't get re-prompted to
    # download 15+ GB.
    from jaeger_ai.core.models.host_recommendation import (
        detect_total_memory_gb, classify_tier, recommend_for_tier,
    )
    from jaeger_ai.core.models.local_discovery import (
        discover_local_gguf_files, match_to_registry,
    )
    from jaeger_ai.core.models.model_resolver import (
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
        # Gate on what the operator ACTUALLY picked for awake, not on the
        # tier recommendation. On every tier where the two recommendations
        # coincide (<=8GB and >=64GB) the old `rec.awake != rec.asleep`
        # test hid "same as awake" outright — so an operator who picked a
        # custom or non-recommended awake model could not decline the
        # second model, and got an unwanted download plus a needless
        # deep-think swap.
        allow_same_as_awake=(model_path != rec.asleep.registry_key),
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
            ("allow", "Auto-allow everything  (trusted, unattended deployment)"),
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
            ("gui", "Desktop app — JaegerAI window + menu-bar tray  (recommended)"),
            ("tui", "Terminal — text TUI (`jaeger --tui`)"),
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
        #     ``nodes/whisper_stt/engine/_base.py``), so speexdsp is OPTIONAL on Mac.
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
    elif interaction_mode == "tui":
        # 0.6 Swift-first: a bare ``jaeger`` opens the desktop app when
        # one is built; the terminal TUI is always one flag away. Say so
        # here so the choice isn't read as "bare `jaeger` opens the TUI".
        print()
        print("     note: a bare `jaeger` opens the desktop app when it's")
        print("           installed — run `jaeger --tui` for the terminal.")

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

    # All the writes live in ``create_instance`` — the single
    # non-interactive core this wizard AND the bridge's onboarding
    # command drive. The wizard passes the RAW role; truncation +
    # soul.md overflow happen inside (same ``_truncate_role``, so the
    # hint printed above matches what lands on disk).
    layout = create_instance(
        character_id=char_id,
        name=name,
        display_name=agent_name,
        role=role_raw,
        personality=personality,
        voice_id=voice_id,
        awake_model=model_path,
        asleep_model=asleep_path,
        permission_mode=perm_mode,
        interaction_mode=interaction_mode,
        voice_enabled=voice_enable_choice,
        make_default=False,     # asked interactively below
    )
    # INST-4: populate the per-instance HOME jail if the user opted
    # in. Idempotent; safe to re-run.
    if use_instance_home:
        from jaeger_ai.core.instance.subprocess_env import populate_instance_home
        populate_instance_home(
            layout,
            git_name=git_name,
            git_email=git_email,
            ssh_key_source=ssh_key_source,
        )

    # Make this the default agent a bare `jaeger` runs? Default YES — you set
    # up an agent in order to run it. Writes the sticky active-instance pointer
    # so a bare `jaeger` resolves here without an --instance flag.
    if _ask_yn("\n  Make this the default agent (a bare `jaeger` runs it)?",
               True):
        from jaeger_ai.core.instance.instance import write_active_instance
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
        print(f"  Re-config: jaeger agent create --force --name {name}")
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
        from jaeger_ai.main import _pipeline, boot_for_tui
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


# ── the non-interactive core (shared with the bridge's onboarding) ──


def _slug(display_name: str) -> str:
    """A clean instance-folder name from an agent display name."""
    import re
    return (re.sub(r"[^a-z0-9_-]+", "-", display_name.strip().lower())
            .strip("-_") or "agent")


def setup_defaults() -> dict:
    """Everything a non-interactive setup surface needs to render its
    choices — served over the bridge as the ``setup_defaults`` query so
    the native app's onboarding shows the same recommendations the CLI
    wizard prints. Read-only; safe pre-instance."""
    from jaeger_ai.core.models.host_recommendation import (
        classify_tier, detect_total_memory_gb, recommend_for_tier,
    )
    from jaeger_ai.core.models.local_discovery import (
        discover_local_gguf_files, match_to_registry,
    )
    detected_gb = detect_total_memory_gb()
    rec = recommend_for_tier(classify_tier(detected_gb))
    by_key = match_to_registry(discover_local_gguf_files())

    def _pick(entry) -> dict:
        found = by_key.get(entry.registry_key)
        return {
            "key": entry.registry_key,
            "display_name": entry.display_name,
            "size_gb": round(float(entry.size_gb), 1),
            "notes": entry.notes,
            "found_locally": found is not None,
            "source": found.source if found is not None else None,
        }

    rows = _character_rows()
    return {
        "host_memory_gb": round(float(detected_gb), 1),
        "tier_label": rec.tier_label,
        "tier_description": rec.description,
        "awake": _pick(rec.awake),
        "asleep": _pick(rec.asleep),
        "voices": [{"id": vid, "label": label} for vid, label in _VOICES],
        "default_character": ("assistant" if any(r[0] == "assistant" for r in rows)
                              else (rows[0][0] if rows else None)),
        "permission_modes": [
            {"id": "confirm", "label": "Ask me before each action"},
            {"id": "allow", "label": "Auto-allow everything"},
        ],
    }


def _configured_provider_lane(
    provider: str, model_id: str, models: list[dict],
) -> str:
    """Map a stored provider name onto the catalog lane that owns its model."""
    if provider != "ollama":
        return provider
    matching_providers = {m["provider"] for m in models if m["id"] == model_id}
    return "ollama-cloud" if "ollama-cloud" in matching_providers else "ollama-local"


def onboarding_model_matrix(layout: InstanceLayout | None = None) -> dict:
    """Complete provider and model matrix for first-run onboarding."""
    from jaeger_ai.core.models.discovery import discover_ollama
    from jaeger_ai.core.models.host_recommendation import (
        classify_tier,
        detect_total_memory_gb,
        recommend_for_tier,
    )
    from jaeger_ai.core.models.model_resolver import (
        MODEL_REGISTRY,
        _resolve_provider_key,
    )

    detected_gb = detect_total_memory_gb()
    rec = recommend_for_tier(classify_tier(detected_gb))

    ollama_res = discover_ollama()
    ollama_online = bool(ollama_res.get("online"))
    ollama_models = ollama_res.get("models") or []

    anthropic_key = _resolve_provider_key("anthropic")
    openai_key = _resolve_provider_key("openai")
    gemini_key = _resolve_provider_key("gemini")
    xai_key = _resolve_provider_key("xai")
    ollama_cloud_key = _resolve_provider_key("ollama-cloud")

    providers = [
        {
            "id": "ollama-local",
            "name": "Ollama (Local)",
            "kind": "local",
            "status": "connected" if ollama_online else "offline",
            "endpoint": str(ollama_res.get("endpoint") or "http://localhost:11434"),
            "requires_key": False,
            "env_var": "OLLAMA_HOST",
            "description": "Local neural server running on this Mac",
        },
        {
            "id": "in-process",
            "name": "Local GGUF / MLX",
            "kind": "local",
            "status": "available",
            "endpoint": "Apple Silicon Unified Memory",
            "requires_key": False,
            "env_var": "",
            "description": "In-process native execution via Metal acceleration",
        },
        {
            "id": "ollama-cloud",
            "name": "Ollama Cloud",
            "kind": "cloud",
            "status": "connected" if (ollama_online or ollama_cloud_key) else "offline",
            "endpoint": "https://ollama.com",
            "requires_key": False,
            "env_var": "OLLAMA_API_KEY",
            "description": "Cloud frontier models through Ollama",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "kind": "cloud",
            "status": "configured" if anthropic_key else "needs_key",
            "endpoint": "https://api.anthropic.com",
            "requires_key": True,
            "env_var": "ANTHROPIC_API_KEY",
            "description": "Claude 3.5 Sonnet, Haiku, Opus",
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "kind": "cloud",
            "status": "configured" if openai_key else "needs_key",
            "endpoint": "https://api.openai.com",
            "requires_key": True,
            "env_var": "OPENAI_API_KEY",
            "description": "GPT-4o, GPT-4o-mini, o1, o3-mini",
        },
        {
            "id": "gemini",
            "name": "Google Gemini",
            "kind": "cloud",
            "status": "configured" if gemini_key else "needs_key",
            "endpoint": "https://generativelanguage.googleapis.com",
            "requires_key": True,
            "env_var": "GEMINI_API_KEY",
            "description": "Gemini 2.5 Pro, Flash (1M+ context)",
        },
        {
            "id": "xai",
            "name": "xAI Grok",
            "kind": "cloud",
            "status": "configured" if xai_key else "needs_key",
            "endpoint": "https://api.x.ai",
            "requires_key": True,
            "env_var": "XAI_API_KEY",
            "description": "Grok 2 real-time frontier reasoning",
        },
    ]

    models: list[dict] = []
    rec_awake_key = rec.awake.registry_key
    rec_asleep_key = rec.asleep.registry_key

    def _probe_ollama_ctx(endpoint: str, model_name: str) -> int:
        import urllib.request
        try:
            url = endpoint.rstrip("/") + "/api/show"
            req = urllib.request.Request(
                url,
                data=json.dumps({"name": model_name}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for k, v in (data.get("model_info") or {}).items():
                    if "context_length" in k and isinstance(v, int) and v > 0:
                        return v
        except Exception:
            pass
        low = model_name.lower()
        if "gemini" in low or "glm" in low:
            return 1048576
        if "26b" in low or "35b" in low or "31b" in low or "mlx" in low:
            return 262144
        if "gemma" in low or "qwen3" in low:
            return 131072
        return 32768

    for key, info in MODEL_REGISTRY.items():
        # The bundled OS utility model is infrastructure, not the identity's
        # primary/fallback intelligence. Surface it through
        # system_utility_status, not as a misleading agent-model choice.
        if info.get("role") == "system":
            continue
        is_awake = (key == rec_awake_key)
        is_asleep = (key == rec_asleep_key)
        ctx_len = info.get("ctx") or 131072
        models.append({
            "id": key,
            "name": info.get("hf_file", key).replace(".gguf", ""),
            "provider": "in-process",
            "provider_label": "Local GGUF",
            "location": "local",
            "size_gb": info.get("size_gb"),
            "context_length": ctx_len,
            "role": info.get("role", "general"),
            "speed": "Real-Time (<200ms)" if info.get("role") == "realtime" else "Deep Reasoning",
            "description": info.get("description", ""),
            "is_recommended_primary": is_awake,
            "is_recommended_fallback": is_asleep,
            "is_chat_model": True,
        })

    ollama_ep = str(ollama_res.get("endpoint") or "http://localhost:11434")

    for m in ollama_models:
        name = m.get("name", "")
        if not name:
            continue
        caps = m.get("capabilities", [])
        remote = bool(m.get("remote_host") or m.get("remote_model")) or name.endswith(":cloud") or name.endswith("-cloud")
        role = "general"
        if "embedding" in caps:
            role = "embedding"
        elif "vision" in caps and not ("completion" in caps or "chat" in caps or "tools" in caps):
            role = "vision"
        elif "thinking" in caps:
            role = "deep_think"
        elif remote:
            role = "general"
        elif (m.get("size_gb") or 0) > 15:
            role = "deep_think"
        else:
            role = "realtime"

        ctx_len = _probe_ollama_ctx(ollama_ep, name)
        is_chat = (role != "embedding")

        if remote:
            models.append({
                "id": name,
                "name": name,
                "provider": "ollama-cloud",
                "provider_label": "Ollama Cloud",
                "location": "cloud",
                "size_gb": None,
                "context_length": ctx_len,
                "role": role,
                "speed": f"Fast Cloud ({ctx_len // 1024}K ctx)",
                "description": f"Ollama Cloud model ({', '.join(caps) or 'cloud'}). Native context: {ctx_len:,} tokens.",
                "is_recommended_primary": False,
                "is_recommended_fallback": False,
                "is_chat_model": is_chat,
            })
        else:
            size = m.get("size_gb")
            models.append({
                "id": name,
                "name": name,
                "provider": "ollama-local",
                "provider_label": "Ollama (Local)",
                "location": "local",
                "size_gb": size,
                "context_length": ctx_len,
                "role": role,
                "speed": "Local Metal Acceleration",
                "description": f"Installed in local Ollama daemon ({size or '?'} GB). Capabilities: {', '.join(caps) or 'chat'}. Native context: {ctx_len:,} tokens.",
                "is_recommended_primary": False,
                "is_recommended_fallback": False,
                "is_chat_model": is_chat,
            })

    cloud_curated_specs = [
        ("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet", "anthropic", "Anthropic", 200000, "deep_think", "Fast & Intelligent", "Frontier reasoning, state-of-the-art coding and agentic tool execution."),
        ("claude-3-5-haiku-latest", "Claude 3.5 Haiku", "anthropic", "Anthropic", 200000, "realtime", "Ultra-Fast (<150ms)", "High-speed conversational turns with exceptional responsiveness and tool use."),
        ("claude-3-opus-latest", "Claude 3 Opus", "anthropic", "Anthropic", 200000, "deep_think", "Deep Reasoning", "Complex deep analysis, long-form synthesis, and deep research."),
        ("gpt-4o", "GPT-4o", "openai", "OpenAI", 128000, "general", "Fast (<250ms)", "Flagship multimodal intelligence, balanced high speed and reasoning."),
        ("gpt-4o-mini", "GPT-4o mini", "openai", "OpenAI", 128000, "realtime", "Ultra-Fast (<150ms)", "Fast, lightweight, low-latency companion model for continuous turns."),
        ("o1", "o1 (Reasoning)", "openai", "OpenAI", 200000, "deep_think", "Deep Reasoning", "Advanced STEM, algorithmic and multi-step reasoning with thinking tokens."),
        ("o3-mini", "o3-mini", "openai", "OpenAI", 200000, "deep_think", "Fast Reasoning", "High-throughput STEM and coding reasoning model."),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", "Google Gemini", 1048576, "deep_think", "Deep Reasoning", "Massive 1M+ context window with leading multimodal understanding and coding."),
        ("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "Google Gemini", 1048576, "realtime", "Ultra-Fast (<150ms)", "High throughput, lightweight, low-latency turns with 1M context."),
        ("gemini-2.0-flash", "Gemini 2.0 Flash", "gemini", "Google Gemini", 1048576, "realtime", "Ultra-Fast (<150ms)", "Next-generation fast multimodal foundation model."),
        ("grok-2-latest", "Grok 2", "xai", "xAI Grok", 131072, "deep_think", "Fast (<300ms)", "State-of-the-art reasoning with real-time knowledge and tool use."),
        ("grok-beta", "Grok Beta", "xai", "xAI Grok", 131072, "general", "Fast (<250ms)", "Direct, unfiltered analytical intelligence."),
    ]

    for model_id, name, prov_id, prov_label, ctx, role, speed, desc in cloud_curated_specs:
        models.append({
            "id": model_id,
            "name": name,
            "provider": prov_id,
            "provider_label": prov_label,
            "location": "cloud",
            "size_gb": None,
            "context_length": ctx,
            "role": role,
            "speed": speed,
            "description": desc,
            "is_recommended_primary": False,
            "is_recommended_fallback": False,
            "is_chat_model": True,
        })

    # Read live configured stack from active instance
    configured_stack = None
    try:
        from jaeger_ai.core.instance.instance import read_active_instance, resolve_instance_dir
        from jaeger_ai.core.instance.schemas import load_yaml, Config
        active_name = layout.root.name if layout is not None else (read_active_instance() or "jaeger")
        active_dir = layout.root if layout is not None else resolve_instance_dir(active_name)
        active_cfg_path = active_dir / "config.yaml"
        if active_cfg_path.is_file():
            cfg = load_yaml(active_cfg_path, Config)
            primary_model = cfg.external_model.model if (cfg.external_model and cfg.external_model.enabled and cfg.external_model.model) else (cfg.model.model_path or "")
            primary_model = str(primary_model)
            primary_provider = cfg.external_model.provider if (cfg.external_model and cfg.external_model.enabled) else "in-process"
            primary_endpoint = cfg.external_model.base_url if (cfg.external_model and cfg.external_model.enabled) else "Local Engine"
            fallback_model = ""
            fallback_provider = ""
            if cfg.external_model and cfg.external_model.fallback:
                fb = cfg.external_model.fallback[0]
                fallback_model = getattr(fb, "model", "")
                fallback_provider = getattr(fb, "provider", "")

            coder_model = str(cfg.deep_think.coder_model or "") if cfg.deep_think else ""
            tts_engine = cfg.voice.speech_engine if cfg.voice else "kokoro"
            tts_voice = cfg.kokoro_tts.voice if cfg.kokoro_tts else "af_heart"
            tts_lang = cfg.kokoro_tts.lang if cfg.kokoro_tts else "a"
            stt_engine = "whisper_stt"
            stt_mode = cfg.whisper_stt.stt_mode if cfg.whisper_stt else "two_pass"
            stt_fast = cfg.whisper_stt.fast_model_name if cfg.whisper_stt else "base.en"
            stt_accurate = cfg.whisper_stt.accurate_model_name if cfg.whisper_stt else "medium.en"
            voice_enabled = bool(cfg.voice and cfg.voice.enabled)

            # Vision & Embedding models from discovered Ollama models
            vision_model = next((m.get("name") for m in ollama_models if "vision" in m.get("capabilities", [])), "minicpm-v:latest")
            embedding_model = next((m.get("name") for m in ollama_models if "embedding" in m.get("capabilities", [])), "mxbai-embed-large:latest")

            configured_stack = {
                "instance_name": active_name,
                "primary_model": primary_model,
                "primary_provider": primary_provider,
                "primary_endpoint": primary_endpoint,
                "fallback_model": fallback_model,
                "fallback_provider": fallback_provider,
                "coder_model": coder_model,
                "tts_engine": tts_engine,
                "tts_voice": tts_voice,
                "tts_lang": tts_lang,
                "stt_engine": stt_engine,
                "stt_mode": stt_mode,
                "stt_fast_model": stt_fast,
                "stt_accurate_model": stt_accurate,
                "vision_model": vision_model,
                "embedding_model": embedding_model,
                "voice_enabled": voice_enabled,
            }
    except Exception:
        pass

    if configured_stack:
        # Ollama is both a local server and a gateway to hosted models.
        # Resolve the provider from discovery rather than labeling every
        # Ollama-backed selection as local.
        configured_provider = _configured_provider_lane(
            configured_stack["primary_provider"],
            configured_stack["primary_model"],
            models,
        )
        configured_stack["primary_provider"] = configured_provider
        if not any(m["id"] == configured_stack["primary_model"] and
                   m["provider"] == configured_provider for m in models):
            models.append({
                "id": configured_stack["primary_model"],
                "name": configured_stack["primary_model"],
                "provider": configured_provider,
                "provider_label": configured_provider,
                "location": "local" if configured_provider in {"in-process", "ollama-local"} else "cloud",
                "size_gb": None, "context_length": None, "role": "general",
                "speed": "", "description": "Currently configured model",
                "is_recommended_primary": False, "is_recommended_fallback": False,
                "is_chat_model": True,
            })

    # Mark configured state on discovered models
    for m in models:
        m["is_configured"] = bool(configured_stack and (
            m["id"] == configured_stack.get("primary_model") or
            m["id"] == configured_stack.get("fallback_model") or
            m["id"] == configured_stack.get("coder_model")
        ))

    available_tts_voices = [
        {"id": "af_heart", "label": "Heart (American Warm Female)"},
        {"id": "af_bella", "label": "Bella (American Soft Female)"},
        {"id": "af_nicole", "label": "Nicole (American Whisper Female)"},
        {"id": "af_sky", "label": "Sky (American Clear Female)"},
        {"id": "am_adam", "label": "Adam (American Deep Male)"},
        {"id": "am_michael", "label": "Michael (American Crisp Male)"},
        {"id": "bm_george", "label": "George (British Neutral Male)"},
        {"id": "bm_lewis", "label": "Lewis (British Resonant Male)"},
    ]

    available_stt_models = [
        {"id": "tiny.en", "label": "Whisper Tiny (Ultra-Fast Wake)"},
        {"id": "base.en", "label": "Whisper Base (Fast & Balanced)"},
        {"id": "small.en", "label": "Whisper Small (Enhanced Accuracy)"},
        {"id": "medium.en", "label": "Whisper Medium (High Accuracy)"},
        {"id": "large-v3-turbo", "label": "Whisper Large Turbo (Max Accuracy)"},
    ]

    return {
        "host_memory_gb": round(float(detected_gb), 1),
        "tier_label": rec.tier_label,
        "tier_description": rec.description,
        # These keys describe the host recommendation. The active selection
        # is carried separately in ``configured``; conflating the two made
        # clients display contradictory recommendations.
        "recommended_primary_key": rec_awake_key,
        "recommended_fallback_key": rec_asleep_key,
        "providers": providers,
        "models": models,
        "configured": configured_stack,
        "available_tts_voices": available_tts_voices,
        "available_stt_models": available_stt_models,
    }


def create_instance(
    *,
    character_id: str,
    name: str | None = None,
    display_name: str | None = None,
    user_name: str | None = None,
    custom_prime_directive: str | None = None,
    role: str | None = None,
    personality: str | None = None,
    voice_id: str | None = None,
    awake_model: str | None = None,
    awake_provider: str | None = None,
    asleep_model: str | None = None,
    permission_mode: str = "confirm",
    interaction_mode: str = "gui",
    voice_enabled: bool = False,
    make_default: bool = True,
    overwrite: bool = False,
) -> InstanceLayout:
    """Create a complete instance non-interactively — THE single write
    path for first-run setup. ``run_wizard`` collects answers in the
    terminal and calls this; the bridge's ``create_instance`` command
    passes the native onboarding's answers straight through. Every
    unset field falls back exactly like the wizard's Enter-through
    defaults: identity from the character sheet, models from the host
    tier recommendation.

    Raises ``LookupError`` for an unknown character and
    ``FileExistsError`` when the target instance already exists and overwrite is False."""
    shim = _character_shim(character_id)
    # Never-empty guarantee: an explicit display_name wins, else the
    # character's, else the hard-coded "Jaeger" — a malformed character
    # sheet (empty display_name) must never leave identity.yaml with a
    # blank name.
    display_name = ((display_name or "").strip()
                    or (shim.display_name or "").strip()
                    or "Jaeger")
    role_raw = (role or "").strip() or shim.role
    role_final, role_overflow = _truncate_role(role_raw)
    personality = ((personality or "").strip()
                   or shim.personality)
    voice_id = (voice_id or "").strip() or shim.voice_id or _VOICES[0][0]
    name = (name or "").strip() or _slug(display_name)

    from jaeger_ai.core.instance.instance import backup_instance_dir
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if layout.exists():
        if overwrite:
            backup_instance_dir(layout)
        else:
            raise FileExistsError(
                f"instance {name!r} already exists at {layout.root}")

    # Models: fall back to the host-tier recommendation; when a chosen
    # registry key already exists on disk (LM Studio, HF cache, …),
    # symlink it into the in-repo models dir so the resolver finds it
    # without a Hugging Face round-trip — same as the wizard.
    from jaeger_ai.core.models.host_recommendation import (
        classify_tier, detect_total_memory_gb, recommend_for_tier,
    )
    from jaeger_ai.core.models.local_discovery import (
        discover_local_gguf_files, match_to_registry,
    )
    from jaeger_ai.core.models.model_resolver import (
        ensure_symlink_in_repo_models,
        MODEL_REGISTRY,
    )
    rec = recommend_for_tier(classify_tier(detect_total_memory_gb()))
    awake_model = (awake_model or "").strip() or rec.awake.registry_key
    asleep_model = (asleep_model or "").strip() or rec.asleep.registry_key
    by_key = match_to_registry(discover_local_gguf_files())
    for key in dict.fromkeys((awake_model, asleep_model)):  # ordered unique
        if key in by_key:
            ensure_symlink_in_repo_models(by_key[key].path, registry_key=key)

    identity = Identity(
        name=display_name, role=role_final,
        personality=personality,
        voice_tone=shim.voice_tone or "clear, even-keeled",
        voice_id=voice_id,
    )
    from jaeger_ai.core.instance.schemas import DeepThinkConfig, VoiceConfig

    is_in_process = awake_model in MODEL_REGISTRY or awake_model.endswith(".gguf")
    # Native capacity is not an allocation budget: keep first boot at 32K.
    awake_ctx = min(MODEL_REGISTRY.get(awake_model, {}).get("ctx") or 32768, 32768)

    config = Config(
        instance_name=name,
        model=ModelConfig(model_path=awake_model, ctx=awake_ctx, gpu_layers=-1),
        display=DisplayConfig(),
        skills=SkillsConfig(),
        retention=RetentionConfig(),
        # The asleep model swaps in during deep-think; "same as awake"
        # (equal values) disables the swap.
        deep_think=DeepThinkConfig(coder_model=asleep_model),
        warmup=WarmupConfig(tts=True, stt=True, vision=False),
        permissions=PermissionsConfig(mode=permission_mode),
        interaction=InteractionConfig(default_mode=interaction_mode),
        voice=VoiceConfig(enabled=voice_enabled),
    )

    # The selected provider is part of the model identity. Never infer a
    # vendor from an Ollama tag (e.g. gemini/claude cloud models).
    from jaeger_ai.core.models.configuration import selected_model_config
    provider = (awake_provider or "").strip()
    if not provider:
        if is_in_process:
            provider = "local"
        elif ":" in awake_model or awake_model.endswith("-cloud"):
            provider = "ollama"
        elif awake_model.startswith("claude"):
            provider = "anthropic"
        elif awake_model.startswith(("gpt", "o1", "o3")):
            provider = "openai"
        elif awake_model.startswith("gemini"):
            provider = "gemini"
        elif awake_model.startswith("grok"):
            provider = "xai"
        else:
            provider = "ollama"
    config, _, _ = selected_model_config(config, provider=provider, model=awake_model)
    # The asleep model is a background role, not an external failover target.
    manifest = Manifest(instance_name=name, schema_version=SCHEMA_VERSION,
                        bound_character=character_id)

    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, identity)
    dump_yaml(layout.config_path, config)
    dump_json(layout.manifest_path, manifest)
    # Mark new identities before migration can mistake identity.yaml for
    # evidence that this operator has already completed the welcome.
    from jaeger_ai.core.instance.first_boot import (
        begin,
        record_bench,
        record_character,
        record_model_selection,
    )
    begin(layout)
    record_model_selection(layout, provider, awake_model)
    # Instance creation already follows model + character selection. Carry
    # those answered stages into first boot so OS initialization resumes at
    # the character's handoff (preset) or the Assistant's guided interview.
    record_bench(layout)
    record_character(
        layout,
        "custom" if character_id == "assistant" else "preset",
        character_id=character_id,
    )
    # Characters are the persona — wire the instance to the chosen one
    # so the running agent plays it (identity / soul / traits / voice).
    from jaeger_ai.personality.character import set_active_character
    set_active_character(layout.root, character_id)
    # INST-3: record install provenance per instance. ``jaeger update``
    # rewrites ``last_updated_with_framework``; ``jaeger restore``
    # rewrites ``install_method`` + adds ``restored_from``.
    from jaeger_ai import __version__ as _jver
    from jaeger_ai.core.instance.instance import detect_install_method
    install_method = detect_install_method()
    dump_yaml(layout.distribution_path, DistributionConfig(
        created_with_framework=_jver,
        last_updated_with_framework=_jver,
        install_method=install_method,
        install_source=_install_source_for(install_method),
    ))
    # soul.md only when the role overflowed identity.role's cap — the
    # character's own soul lives in its character sheet.
    _initialise_soul_md(layout.root, display_name,
                        persona_soul=None, role_overflow=role_overflow)
    _git_init(layout.root)
    # WIZ-4: a sourceable env file so shells can pin this instance
    # without memorising the path.
    _write_env_file(layout.root, name)
    if user_name or custom_prime_directive:
        from jaeger_agent.memory.sqlite_store import seed_facts
        facts = {}
        if user_name and user_name.strip():
            facts["name"] = user_name.strip()
        if custom_prime_directive and custom_prime_directive.strip():
            facts["custom_prime_directive"] = custom_prime_directive.strip()
        seed_facts(layout, facts)
    if make_default:
        from jaeger_ai.core.instance.instance import write_active_instance
        write_active_instance(name)
    return layout


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
    operator state at ``<install_root>/.jaeger_ai/jaeger.env``."""
    from jaeger_ai.core.instance.instance import operator_state_root
    return operator_state_root() / "jaeger.env"


def _write_env_file(instance_root: Path, instance_name: str) -> None:
    """Persist ``export JAEGER_INSTANCE_DIR=…`` (+ INSTANCE_NAME) at
    ``<install_root>/.jaeger_ai/jaeger.env`` so the user has a single,
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
