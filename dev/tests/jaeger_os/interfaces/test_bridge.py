"""NDJSON stdio bridge protocol — the contract the Swift shell parses.

Phase-1 hardened contract (SWIFT_APP_ARCHITECTURE_PLAN.md): FAST READY
(transport usable before the model boots, ``agent_state`` streams the
transition), worker-thread turns, interactive permission ``request`` /
``respond``, and the ``bye`` clean-exit marker. These tests fake
``boot_for_tui`` + ``run_for_voice`` so we pin the *protocol* without
booting a multi-GB model. The frame SHAPES are pinned separately against
``protocol_v1_fixtures.json`` (the cross-language fixtures Swift also
tests against).
"""

from __future__ import annotations

import io
import json
import time

import pytest

from jaeger_os.interfaces import bridge, protocol


class _FakeBoot:
    def __init__(self):
        self.client = object()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


@pytest.fixture(autouse=True)
def _instance_on_disk(tmp_path, monkeypatch):
    """``bridge.main`` refuses to boot when the resolved instance doesn't
    exist (fatal kind=``no_instance`` — the first-run signal the native
    app's onboarding runs on). Give every test a minimal on-disk instance
    (the identity/config/manifest trio ``InstanceLayout.exists()`` checks)
    so the faked-boot paths exercise the normal flow; the no-instance
    tests below override ``JAEGER_INSTANCE_DIR`` to a missing dir."""
    root = tmp_path / "inst"
    root.mkdir()
    for f in ("identity.yaml", "config.yaml", "manifest.json"):
        (root / f).write_text("{}", encoding="utf-8")
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(root))
    return root


def test_effective_icon_prefers_instance_avatar_over_character_card(tmp_path):
    """The agent's face is instance-owned: identity.avatar wins when set +
    present; otherwise the active character's card is the default."""
    import types

    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.core.instance.schemas import Identity, dump_yaml
    from jaeger_os.interfaces import bridge

    lay = InstanceLayout(root=tmp_path / "inst2")
    lay.root.mkdir(parents=True)
    lay.ensure_dirs()
    card = tmp_path / "card.png"
    card.write_bytes(b"x")
    char = types.SimpleNamespace(icon_path=lambda: card)
    boot = types.SimpleNamespace(layout=lay)

    # No instance avatar → the character card is the default face.
    dump_yaml(lay.identity_path, Identity(name="Ted", role="r", personality="p"))
    assert bridge._effective_icon(boot, char) == str(card)

    # A custom instance avatar (relative to the instance dir) wins.
    pic = lay.root / "me.png"
    pic.write_bytes(b"y")
    dump_yaml(lay.identity_path,
              Identity(name="Ted", role="r", personality="p", avatar="me.png"))
    assert bridge._effective_icon(boot, char) == str(pic)

    # A set-but-missing avatar path falls back to the card (never a broken icon).
    dump_yaml(lay.identity_path,
              Identity(name="Ted", role="r", personality="p", avatar="gone.png"))
    assert bridge._effective_icon(boot, char) == str(card)


def test_save_identity_sets_name_and_copies_avatar(tmp_path):
    """The instance settings tab's write: agent NAME + profile PICTURE. The
    picked image is copied INTO the instance dir; a cleared avatar falls back
    to the character card; an illegal name is rejected by the schema."""
    import types

    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.core.instance.schemas import Identity, dump_yaml, load_yaml
    from jaeger_os.interfaces import bridge

    lay = InstanceLayout(root=tmp_path / "inst3")
    lay.root.mkdir(parents=True)
    lay.ensure_dirs()
    dump_yaml(lay.identity_path, Identity(name="jarvis", role="r", personality="p"))
    boot = types.SimpleNamespace(layout=lay, client=None)

    picked = tmp_path / "picked.png"
    picked.write_bytes(b"IMG")
    ok, err = bridge._command("save_identity",
                              {"name": "Ted", "avatar": str(picked)}, boot)
    assert ok, err
    ident = load_yaml(lay.identity_path, Identity)
    assert ident.name == "Ted"
    assert ident.avatar == "avatar.png"           # copied in, stored relative
    assert (lay.root / "avatar.png").is_file()

    # Clearing the avatar keeps the name and falls back to the character card.
    ok, _ = bridge._command("save_identity", {"avatar": ""}, boot)
    assert ok and load_yaml(lay.identity_path, Identity).avatar is None
    assert load_yaml(lay.identity_path, Identity).name == "Ted"

    # A path-illegal name is refused by the Identity validator.
    ok, err = bridge._command("save_identity", {"name": "bad/name"}, boot)
    assert not ok and "path-illegal" in (err or "")


class _SlowStdin:
    """An iterable stdin that holds the FIRST line back briefly — lets a
    test deterministically lose the stdin-vs-boot-thread race (the boot
    wins) instead of depending on scheduler luck."""

    def __init__(self, text: str, first_line_delay: float) -> None:
        self._lines = iter(io.StringIO(text))
        self._delay = first_line_delay

    def __iter__(self):
        return self

    def __next__(self):
        if self._delay:
            time.sleep(self._delay)
            self._delay = 0.0
        return next(self._lines)


def _run(monkeypatch, stdin_text, *, run_reply=None, boot_exc=None,
         boot_delay=0.0, run_fn=None, stdin_delay=0.0, argv=None,
         default_name="test-inst"):
    """Drive ``bridge.main`` with faked deps; return parsed stdout frames.

    ``argv`` mirrors what the Swift shell passes on the ``jaeger bridge``
    command line (``["lilith"]`` when ``JAEGER_INSTANCE_NAME`` is pinned
    non-empty); ``default_name`` is what a bareword launch's
    ``default_instance_name()`` resolves to when no explicit argv is
    given — real installs return the literal ``"default"`` here on a
    genuinely fresh box."""
    boot = _FakeBoot()

    def fake_boot(*, instance_name, **kwargs):
        # ``**kwargs`` absorbs prewarm_model=False (the bridge skips the
        # generic prewarm and runs the prefix-exact prewarm_session — which
        # no-ops here because the fake client has no ``.llm``).
        if boot_delay:
            time.sleep(boot_delay)
        if boot_exc:
            raise boot_exc
        # The real TUIBootResult carries the layout — post-boot queries
        # (instance_exists, config, …) read it off the boot object.
        from jaeger_os.core.instance.instance import (
            InstanceLayout, resolve_instance_dir)
        boot.layout = InstanceLayout(resolve_instance_dir(instance_name))
        return boot

    def fake_run(client, text, session_key=None):
        return run_reply or {"text": f"echo:{text}", "error": None}

    monkeypatch.setattr("jaeger_os.main.boot_for_tui", fake_boot, raising=False)
    monkeypatch.setattr("jaeger_os.main.run_for_voice", run_fn or fake_run,
                        raising=False)
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.default_instance_name",
        lambda: default_name, raising=False,
    )

    proto = io.StringIO()
    monkeypatch.setattr("sys.stdout", proto)
    monkeypatch.setattr("sys.stdin", _SlowStdin(stdin_text, stdin_delay))

    rc = bridge.main(argv=argv if argv is not None else [])
    frames = [json.loads(ln) for ln in proto.getvalue().splitlines() if ln.strip()]
    return rc, frames, boot


def test_fast_ready_then_agent_state_then_turn(monkeypatch):
    rc, frames, boot = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n')
    assert rc == 0
    types = [f["type"] for f in frames]
    # FAST READY: transport first, agent streams in behind, bye marks
    # the orderly exit.
    assert types == ["ready", "agent_state", "agent_state",
                     "state", "reply", "state", "bye"]
    ready = frames[0]
    assert ready["instance"] == "test-inst"
    assert ready["proto"] == protocol.PROTOCOL_VERSION
    assert ready["agent"] == "booting"
    assert set(protocol.CAPABILITIES) == set(ready["capabilities"])
    assert frames[1]["state"] == "booting"
    assert frames[2]["state"] == "ready"
    assert frames[4] == {"type": "reply", "text": "echo:hi", "error": None,
                         "session": "desktop-app"}
    assert frames[6]["type"] == "bye"
    assert boot.cleaned is True  # graceful teardown ran


def test_session_key_flows_through(monkeypatch):
    seen = {}

    def run_fn(client, text, session_key=None):
        seen["session"] = session_key
        return {"text": "ok", "error": None}

    _run(monkeypatch,
         '{"op":"send","text":"hi","session":"chat-win-2"}\n{"op":"quit"}\n',
         run_fn=run_fn)
    assert seen["session"] == "chat-win-2"


def test_boot_failure_streams_failed_then_fatal(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n',
                         boot_exc=RuntimeError("model file missing"))
    assert rc == 1
    types = [f["type"] for f in frames]
    assert types == ["ready", "agent_state", "agent_state", "fatal", "bye"]
    assert frames[2] == {"type": "agent_state", "state": "failed",
                         "model": None, "character": None, "icon": None,
                         "error": "model file missing", "agent_name": None}
    assert frames[3]["kind"] == "boot"


def test_lock_conflict_gets_the_locked_kind(monkeypatch):
    rc, frames, _ = _run(
        monkeypatch, '{"op":"quit"}\n',
        boot_exc=RuntimeError("instance 'x' is locked by pid 4 (still running)."))
    fatal = next(f for f in frames if f["type"] == "fatal")
    assert fatal["kind"] == "locked"
    assert rc == 1


class _FakeCron:
    """Records the bridge's CronRunner lifecycle without a real thread.
    ``start`` synchronously fires one scheduled prompt so the callback's
    reply-frame surfacing is exercised end-to-end."""

    instances: list["_FakeCron"] = []

    def __init__(self, cb, *, poll_s=30.0, llm_lock=None, housekeeping=None):
        self.cb = cb
        self.llm_lock = llm_lock
        self.started = False
        self.stopped = False
        _FakeCron.instances.append(self)

    def start(self):
        self.started = True
        # Simulate a due schedule firing while the agent is live.
        self.cb("check the logs", session_key="cron:reminder")

    def shutdown(self, wait=True):
        self.stopped = True


def test_bridge_starts_and_stops_cron_and_surfaces_fired_reminder(monkeypatch):
    """Job-1 regression: the bridge must start a CronRunner (so scheduled
    prompts actually fire), surface a fired prompt as a reply frame on its
    ``cron:*`` session, and stop the runner on teardown. Passing the runner
    ``llm_lock=None`` is load-bearing — ``_run_turn`` serializes turns on
    ``_pipeline['llm_lock']`` internally, so handing the SAME lock here
    would deadlock the fired turn."""
    _FakeCron.instances.clear()
    monkeypatch.setattr(
        "jaeger_os.agent.background.cron_runner.CronRunner", _FakeCron,
        raising=False)

    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n')
    assert rc == 0

    assert len(_FakeCron.instances) == 1
    cron = _FakeCron.instances[0]
    assert cron.started is True
    assert cron.stopped is True          # stopped on teardown
    assert cron.llm_lock is None         # no re-entrant deadlock

    # The fired prompt surfaced as a reply frame on the cron session, so a
    # reminder shows up in the chat.
    cron_replies = [f for f in frames
                    if f["type"] == "reply" and f["session"] == "cron:reminder"]
    assert cron_replies, f"no cron reply frame surfaced: {frames}"
    assert cron_replies[0]["text"] == "echo:check the logs"


def test_no_instance_streams_failed_then_no_instance_fatal(monkeypatch, tmp_path):
    """First-run: the resolved instance isn't on disk. The bridge must NOT
    reach ``boot_for_tui`` (which would auto-fire the interactive wizard
    against our protocol stdin — the 0.6 first-run break) — it reports
    ``fatal kind=no_instance`` and keeps the transport alive."""
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    # If boot ran anyway, the faked boot would emit ``agent_state booting``
    # + ``ready`` — the exact frame-sequence assert below catches it.
    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n',
                         boot_exc=AssertionError("boot must not run"))
    types = [f["type"] for f in frames]
    assert types == ["ready", "agent_state", "fatal", "bye"]
    assert frames[1]["state"] == "failed"
    assert "first-run setup required" in frames[1]["error"]
    assert frames[2]["kind"] == "no_instance"
    assert rc == 1


def test_no_instance_fatal_carries_suggested_name_from_explicit_cli_pin(
        monkeypatch, tmp_path):
    """``./jaeger agent create lilith`` pins the operator-typed name onto
    the ``jaeger bridge`` argv (mirroring ``JAEGER_INSTANCE_NAME`` — see
    main.py's ``_launch_swift_app``). The no_instance fatal frame must
    surface it as ``suggested_name`` so onboarding can default the
    identity field to it instead of orphaning it behind whatever
    character gets picked."""
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n',
                         boot_exc=AssertionError("boot must not run"),
                         argv=["lilith"])
    fatal = next(f for f in frames if f["type"] == "fatal")
    assert fatal["kind"] == "no_instance"
    assert fatal["suggested_name"] == "lilith"


def test_no_instance_fatal_omits_suggested_name_for_generic_default(
        monkeypatch, tmp_path):
    """No explicit CLI name → the resolver's generic ``"default"``
    fallback (a fresh box, no sticky, no env pin) must NOT leak into
    onboarding as a suggestion — that would wrongly override the
    character-name default the identity step is supposed to fall back
    to."""
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n',
                         boot_exc=AssertionError("boot must not run"),
                         default_name="default")
    fatal = next(f for f in frames if f["type"] == "fatal")
    assert fatal["kind"] == "no_instance"
    assert "suggested_name" not in fatal


def test_no_instance_transport_still_serves_queries(monkeypatch, tmp_path):
    """Pre-instance the pipe stays useful: queries answer (the native
    onboarding needs characters/setup data over this same transport)."""
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    stdin = '{"op":"query","what":"identity","id":"r1"}\n{"op":"quit"}\n'
    rc, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["ok"] is True
    assert set(result["data"]) == {"agent_name", "character", "icon", "avatar", "model"}
    assert result["data"]["agent_name"] is None   # no identity.yaml yet


def test_instance_exists_query_both_states(monkeypatch, tmp_path,
                                            _instance_on_disk):
    """``instance_exists`` — the first-run probe. True with the fixture's
    on-disk instance; false when the resolution points at nothing."""
    stdin = '{"op":"query","what":"instance_exists","id":"r1"}\n{"op":"quit"}\n'
    _, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["data"] == {"exists": True, "root": str(_instance_on_disk)}

    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    _, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["data"]["exists"] is False


def test_setup_defaults_query_serves_recommendations(monkeypatch, tmp_path):
    """``setup_defaults`` answers pre-instance with the host tier, the
    recommended awake/asleep pair, voices, and a default character — the
    data the native onboarding renders."""
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    stdin = '{"op":"query","what":"setup_defaults","id":"r1"}\n{"op":"quit"}\n'
    _, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["ok"] is True
    data = result["data"]
    assert {"host_memory_gb", "tier_label", "awake", "asleep", "voices",
            "default_character", "permission_modes"} <= set(data)
    assert data["awake"]["key"]
    assert data["voices"] and {"id", "label"} == set(data["voices"][0])


def test_create_instance_command_writes_instance_and_boots(monkeypatch, tmp_path):
    """First-run onboarding end-to-end over the pipe: no instance →
    ``create_instance`` writes a schema-valid instance (same core the CLI
    wizard drives) → the bridge boots it, streaming agent_state booting →
    ready as the client's live progress."""
    inst_dir = tmp_path / "fresh-inst"
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(inst_dir))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "opstate"))
    # No git shell-out for the instance repo in the unit walk.
    from jaeger_os.core.instance import setup_wizard as W
    monkeypatch.setattr(W, "_git_init", lambda root: None)

    stdin = ('{"op":"command","cmd":"create_instance",'
             '"args":{"character_id":"jarvis","display_name":"Jarvis"},'
             '"id":"r1"}\n'
             '{"op":"quit"}\n')
    rc, frames, _ = _run(monkeypatch, stdin)
    types = [f["type"] for f in frames]
    # no-instance handshake, then the create result, then a REAL boot.
    assert types == ["ready", "agent_state", "fatal",
                     "result", "agent_state", "agent_state", "bye"]
    result = frames[3]
    assert result["ok"] is True
    assert result["data"]["root"] == str(inst_dir)
    assert frames[4]["state"] == "booting"
    assert frames[5]["state"] == "ready"
    assert rc == 0   # boot_error cleared by the restart

    # The instance on disk is complete and schema-valid.
    from jaeger_os.core.instance.schemas import (
        Config, Identity, Manifest, load_json, load_yaml)
    ident = load_yaml(inst_dir / "identity.yaml", Identity)
    cfg = load_yaml(inst_dir / "config.yaml", Config)
    man = load_json(inst_dir / "manifest.json", Manifest)
    assert ident.name == "Jarvis"
    assert cfg.permissions.mode == "confirm"
    assert man.bound_character == "jarvis"
    assert (inst_dir / "active_character").read_text().strip() == "jarvis"


def test_create_instance_requires_character(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "missing"))
    stdin = ('{"op":"command","cmd":"create_instance","args":{},"id":"r1"}\n'
             '{"op":"quit"}\n')
    _, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["ok"] is False
    assert "character_id" in result["error"]


def test_turn_during_failed_boot_reports_error(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n',
                         boot_exc=RuntimeError("nope"))
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply["error"] == "nope"
    assert reply["text"] == ""


def test_malformed_and_blank_lines_ignored(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '\nnot json\n{"text":"  "}\n{"op":"quit"}\n')
    # No turn frames — blank/garbage/empty-text lines produce nothing.
    assert [f["type"] for f in frames] == ["ready", "agent_state",
                                           "agent_state", "bye"]
    assert rc == 0


def test_turn_error_is_reported_not_raised(monkeypatch):
    rc, frames, _ = _run(
        monkeypatch, '{"text":"x"}\n{"op":"quit"}\n',
        run_reply={"text": "", "error": "model exploded"},
    )
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply == {"type": "reply", "text": "", "error": "model exploded",
                     "session": "desktop-app"}
    assert rc == 0


def test_permission_request_respond_roundtrip(monkeypatch):
    """A tool asking for approval mid-turn emits ``request``; the client's
    ``respond`` op resolves it — allow reaches the tool as True. Proves the
    stdin thread stays free while a turn blocks on the answer."""
    from jaeger_os.core.safety.permissions import current_policy
    original = current_policy().confirmation
    answers = {}

    def run_fn(client, text, session_key=None):
        # Simulate a gated tool consulting the policy mid-turn (this runs
        # on the TURN thread, exactly like the real permission path).
        answers["granted"] = current_policy().confirmation.confirm(
            type("Req", (), {"skill": "files", "operation": "write_file"})())
        return {"text": "done", "error": None}

    # respond arrives AFTER the turn starts.
    stdin = ('{"text":"write it"}\n'
             '{"op":"respond","id":"perm1","answer":"allow"}\n'
             '{"op":"quit"}\n')
    try:
        rc, frames, _ = _run(monkeypatch, stdin, run_fn=run_fn)
    finally:
        current_policy().confirmation = original
    req = next(f for f in frames if f["type"] == "request")
    assert req["kind"] == "approval" and req["id"] == "perm1"
    assert req["options"] == ["allow", "deny"]
    assert answers["granted"] is True
    assert rc == 0


def test_identity_query_roundtrip(monkeypatch, _instance_on_disk):
    """``{"op":"query","what":"identity"}`` answers with a result frame
    carrying agent_name/character/icon/model — the additive read the Swift
    shell uses to refresh tray/header branding. ``agent_name`` is the
    AGENT's own name (identity.yaml — never the character's); surfaces
    lead with it and show the character as secondary flavor."""
    (_instance_on_disk / "identity.yaml").write_text(
        "name: Ted\nrole: assistant\npersonality: plain\n", encoding="utf-8")
    stdin = '{"op":"query","what":"identity","id":"r1"}\n{"op":"quit"}\n'
    rc, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["id"] == "r1"
    assert result["ok"] is True
    assert set(result["data"]) == {"agent_name", "character", "icon", "avatar", "model"}
    assert result["data"]["agent_name"] == "Ted"
    assert rc == 0


def test_speak_command_roundtrip(monkeypatch):
    """``{"op":"command","cmd":"speak"}`` — the native app's speaker button.
    Accepted (ok=True) once the agent is up; the synthesis itself runs
    fire-and-forget on a worker thread via the agent's speak machinery
    (Kokoro + the active character's voice). Empty text is refused."""
    import importlib
    import threading

    spoken = {}
    done = threading.Event()

    def fake_speak(text="", path=""):
        spoken["text"] = text
        done.set()
        return {"spoken": True, "elapsed_s": 0.1, "reason": ""}

    # Patch the MODULE object, not the dotted string: the tools package
    # re-exports a ``speak`` FUNCTION that shadows the submodule on
    # attribute lookup, so the string form patches the wrong object.
    speak_mod = importlib.import_module("jaeger_os.agent.tools.speak")
    monkeypatch.setattr(speak_mod, "speak", fake_speak)
    stdin = ('{"op":"command","cmd":"speak","args":{"text":"Good day."},"id":"r3"}\n'
             '{"op":"command","cmd":"speak","args":{"text":"  "},"id":"r4"}\n'
             '{"op":"quit"}\n')
    # Hold the first command back so the (faked, instant) boot wins the
    # race — this test pins the POST-boot speak path; the pre-boot path
    # has its own test below.
    rc, frames, _ = _run(monkeypatch, stdin, stdin_delay=0.25)
    results = {f["id"]: f for f in frames if f["type"] == "result"}
    assert results["r3"]["ok"] is True
    assert results["r4"]["ok"] is False
    assert "nothing to speak" in results["r4"]["error"]
    assert done.wait(5.0)
    assert spoken["text"] == "Good day."
    assert rc == 0


def test_speak_command_while_booting_reports_not_ready(monkeypatch):
    """Before the model lands there is no agent to route speech through —
    the command reports instead of wedging or crashing."""
    stdin = ('{"op":"command","cmd":"speak","args":{"text":"hi"},"id":"r1"}\n'
             '{"op":"quit"}\n')
    rc, frames, _ = _run(monkeypatch, stdin, boot_delay=0.5)
    result = next(f for f in frames if f["type"] == "result")
    assert result["ok"] is False
    assert "booting" in result["error"]
    assert rc == 0


def test_config_query_carries_speech_engine(monkeypatch):
    """The Swift shell routes its speaker button on ``speech_engine`` read
    over the existing config query — pin the field's presence + default."""
    import io as _io
    import pathlib
    import tempfile

    from jaeger_os.core.instance.schemas import (
        Config, Identity, ModelConfig, dump_yaml)

    tmp = pathlib.Path(tempfile.mkdtemp())
    dump_yaml(tmp / "config.yaml", Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null")))
    dump_yaml(tmp / "identity.yaml", Identity(
        name="T", role="r", personality="p", voice_tone="v"))

    class _Lay:
        config_path = tmp / "config.yaml"
        identity_path = tmp / "identity.yaml"
        root = tmp

    data = bridge._query("config", {}, type("B", (), {"layout": _Lay()})())
    assert data["speech_engine"] == "kokoro"
    # Display prefs the Swift chat renders by (operator keepers, 2026-07-05).
    assert data["activity_trace"] == "full"
    assert data["turn_separators"] is True

    # save_config roundtrip: both display prefs persist.
    ok, err = bridge._command(
        "save_config",
        {"activity_trace": "summary", "turn_separators": False},
        type("B", (), {"layout": _Lay()})())
    assert ok and err is None
    data = bridge._query("config", {}, type("B", (), {"layout": _Lay()})())
    assert data["activity_trace"] == "summary"
    assert data["turn_separators"] is False


def test_config_query_carries_context_window_knobs(monkeypatch):
    """v1 additive — ``model_ctx`` (worker lane) and ``model_aux_ctx``
    (aux lane: persona filter / finalizer / reflection side calls) ride
    the existing config query + save_config, HUD-ready. Both apply on
    restart; the bridge only persists them."""
    import pathlib
    import tempfile

    from jaeger_os.core.instance.schemas import (
        Config, Identity, ModelConfig, dump_yaml, load_yaml)

    tmp = pathlib.Path(tempfile.mkdtemp())
    dump_yaml(tmp / "config.yaml", Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null")))
    dump_yaml(tmp / "identity.yaml", Identity(
        name="T", role="r", personality="p", voice_tone="v"))

    class _Lay:
        config_path = tmp / "config.yaml"
        identity_path = tmp / "identity.yaml"
        root = tmp

    data = bridge._query("config", {}, type("B", (), {"layout": _Lay()})())
    assert data["model_ctx"] == 8192       # ModelConfig defaults
    assert data["model_aux_ctx"] == 4096

    # save_config roundtrip: both knobs persist and re-read.
    ok, err = bridge._command(
        "save_config", {"model_ctx": 65_536, "model_aux_ctx": 2048},
        type("B", (), {"layout": _Lay()})())
    assert ok and err is None
    data = bridge._query("config", {}, type("B", (), {"layout": _Lay()})())
    assert data["model_ctx"] == 65_536
    assert data["model_aux_ctx"] == 2048
    cfg = load_yaml(tmp / "config.yaml", Config)
    assert cfg.model.ctx == 65_536 and cfg.model.aux_ctx == 2048

    # Schema bounds still enforced through the bridge (ge=0 / le=131072).
    ok, err = bridge._command(
        "save_config", {"model_ctx": 999_999},
        type("B", (), {"layout": _Lay()})())
    assert not ok and err


def _write_valid_instance(root):
    """Overwrite the fixture's ``{}`` config/identity with schema-valid
    files so the settings catalog (which loads the real ``Config``) works."""
    from jaeger_os.core.instance.schemas import (
        Config, Identity, ModelConfig, dump_yaml)
    dump_yaml(root / "config.yaml",
              Config(instance_name="t", model=ModelConfig(model_path="/dev/null")))
    dump_yaml(root / "identity.yaml",
              Identity(name="T", role="r", personality="p"))


def test_settings_catalog_query_returns_grouped_descriptors(monkeypatch,
                                                            _instance_on_disk):
    """``query what=settings_catalog`` serves the schema-derived catalog the
    native app renders — grouped, typed descriptors, no hand-enumerated list.
    The SAME backend `jaeger settings` drives."""
    _write_valid_instance(_instance_on_disk)
    stdin = ('{"op":"query","what":"settings_catalog","id":"r1"}\n'
             '{"op":"quit"}\n')
    rc, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["ok"] is True
    data = result["data"]
    # The eight spec groups are live.
    assert {"model", "display", "voice", "tts", "autonomy",
            "permissions", "retention", "interaction"} <= set(data)
    engine = next(d for d in data["tts"] if d["path"] == "voice.speech_engine")
    assert engine["type"] == "enum" and engine["choices"] == ["kokoro", "apple"]
    assert rc == 0


def test_settings_set_command_roundtrip(monkeypatch, _instance_on_disk):
    """``command cmd=settings_set`` validates + persists through the Pydantic
    model and reports ``restart_required``. Proves single-source: the write
    lands in config.yaml, readable by every other surface."""
    from jaeger_os.core.instance.schemas import Config, load_yaml
    _write_valid_instance(_instance_on_disk)
    stdin = ('{"op":"command","cmd":"settings_set",'
             '"args":{"path":"voice.speak_replies","value":false},"id":"r1"}\n'
             '{"op":"command","cmd":"settings_set",'
             '"args":{"path":"model.ctx","value":16384},"id":"r2"}\n'
             '{"op":"command","cmd":"settings_set",'
             '"args":{"path":"model.ctx","value":999999},"id":"r3"}\n'
             '{"op":"quit"}\n')
    rc, frames, _ = _run(monkeypatch, stdin)
    results = {f["id"]: f for f in frames if f["type"] == "result"}
    # voice pref: ok, no restart.
    assert results["r1"]["ok"] is True
    assert results["r1"]["data"]["restart_required"] is False
    assert results["r1"]["data"]["value"] is False
    # model.ctx: ok, restart REQUIRED (schema-annotated).
    assert results["r2"]["ok"] is True
    assert results["r2"]["data"]["restart_required"] is True
    # out-of-range rejected through the model — error, not a crash.
    assert results["r3"]["ok"] is False and results["r3"]["error"]
    # Persisted values round-trip; the bad write never landed.
    cfg = load_yaml(_instance_on_disk / "config.yaml", Config)
    assert cfg.voice.speak_replies is False
    assert cfg.model.ctx == 16384
    assert rc == 0


def test_reply_carries_turn_telemetry_when_available(monkeypatch):
    """``run_for_voice`` reports elapsed_s — the bridge forwards it on the
    reply frame (v1 additive). ctx_used/ctx_max are absent here because the
    faked pipeline has no session agent / loaded model — absence, not null,
    is the contract for unknown telemetry."""
    def timed_run(client, text, session_key=None):  # noqa: ARG001
        return {"text": "pong", "error": None, "elapsed_s": 2.5}

    rc, frames, _ = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n',
                         run_fn=timed_run)
    assert rc == 0
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply["text"] == "pong"
    assert reply["elapsed_s"] == 2.5
    assert "ctx_used" not in reply and "ctx_max" not in reply


def test_slash_help_answers_without_an_agent_turn(monkeypatch):
    """A leading ``/`` is a command, not a prompt — ``/help`` renders the
    TUI's command list over the bridge and never reaches run_for_voice."""
    def explode(client, text, session_key=None):  # noqa: ARG001
        raise AssertionError("slash text must not reach the agent turn")

    rc, frames, _ = _run(monkeypatch, '{"text":"/help"}\n{"op":"quit"}\n',
                         run_fn=explode)
    assert rc == 0
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply["error"] is None
    assert "slash commands" in reply["text"]
    assert "/help" in reply["text"]


def test_slash_unsafe_command_reports_tui_only(monkeypatch):
    """Interactive/TUI-bound commands (e.g. /model's picker) don't run over
    the bridge — stdin is the protocol stream — they answer with a pointer."""
    rc, frames, _ = _run(monkeypatch, '{"text":"/model"}\n{"op":"quit"}\n')
    assert rc == 0
    reply = next(f for f in frames if f["type"] == "reply")
    assert "needs the terminal TUI" in reply["text"]
    assert "/help" in reply["text"]          # the safe list is advertised


def test_slash_unknown_command_hints_help(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '{"text":"/zzz"}\n{"op":"quit"}\n')
    assert rc == 0
    reply = next(f for f in frames if f["type"] == "reply")
    assert "Unknown slash command" in reply["text"]


def test_fixture_frames_match_builders():
    """The cross-language fixtures ARE what the builders produce — if a
    builder changes shape, this fails here and the Swift decoder test
    fails there, symmetrically."""
    import pathlib
    fx = json.loads(
        (pathlib.Path(bridge.__file__).parent / "protocol_v1_fixtures.json")
        .read_text())
    frames = fx["frames"]
    assert fx["proto"] == protocol.PROTOCOL_VERSION
    assert frames["ready"] == protocol.ready_frame(
        "jros-dev", None, agent="booting")
    # The split: agent_name (the instance the operator named) is DISTINCT from
    # character (the persona it plays) — "Jarvis playing HAL 9000".
    assert frames["ready_warm"] == protocol.ready_frame(
        "jros-dev", "gemma-4-E4B-it-Q4_K_M.gguf", "HAL 9000",
        "/tmp/hal.png", agent="ready", agent_name="Jarvis")
    assert frames["agent_state_booting"] == protocol.agent_state_frame("booting")
    assert frames["agent_state_ready"] == protocol.agent_state_frame(
        "ready", model="gemma-4-E4B-it-Q4_K_M.gguf",
        character="HAL 9000", icon="/tmp/hal.png", agent_name="Jarvis")
    assert frames["agent_state_failed"] == protocol.agent_state_frame(
        "failed", error="model file missing")
    assert frames["state_busy"] == protocol.state_frame(True, "desktop-app")
    assert frames["state_idle"] == protocol.state_frame(False, "desktop-app")
    assert frames["tool"] == protocol.tool_frame(
        "web_search", "done", 1.25, "desktop-app")
    # v1 additive tool detail — key present only when supplied, so the base
    # "tool" fixture above (no detail key) stays byte-identical.
    assert frames["tool_skill_detail"] == protocol.tool_frame(
        "skill", "start", 0.0, "desktop-app", detail="view scheduling")
    assert "detail" not in protocol.tool_frame("web_search", "done")
    assert frames["reply"] == protocol.reply_frame(
        "It's 3:48 PM PDT.", None, "desktop-app")
    assert frames["reply_error"] == protocol.reply_frame(
        "", "model exploded", "desktop-app")
    # v1 additive reply telemetry — keys present only when supplied, so the
    # base "reply" fixture above (no telemetry keys) stays byte-identical.
    assert frames["reply_telemetry"] == protocol.reply_frame(
        "It's 3:48 PM PDT.", None, "desktop-app",
        elapsed_s=3.21, ctx_used=18300, ctx_max=32768)
    assert "elapsed_s" not in protocol.reply_frame("hi")
    assert frames["request_approval"] == protocol.request_frame(
        "perm1", "approval", "Allow files.write_file?", ("allow", "deny"))
    assert frames["fatal_boot"] == protocol.fatal_frame("model file missing")
    assert frames["fatal_locked"] == protocol.fatal_frame(
        "instance 'jros-dev' is locked by pid 4242 (still running).",
        kind="locked")
    assert frames["fatal_no_instance"] == protocol.fatal_frame(
        "no instance named 'default' exists yet — first-run setup required",
        kind="no_instance")
    # v1 additive suggested_name — omitted by default (fixture above stays
    # byte-identical), present only when the bridge has a real operator
    # pin to hand onboarding.
    assert "suggested_name" not in protocol.fatal_frame(
        "x", kind="no_instance")
    assert frames["fatal_no_instance_suggested"] == protocol.fatal_frame(
        "no instance named 'lilith' exists yet — first-run setup required",
        kind="no_instance", suggested_name="lilith")
    assert frames["bye"] == protocol.bye_frame()
    # v1 additive: the settings_set result carries restart_required in data.
    assert frames["result_settings_set"] == protocol.result_frame(
        "r7", data={"restart_required": True, "path": "model.ctx",
                    "value": 16384}, ok=True)
    assert fx["ops"]["send"] == protocol.send_op("hello", "desktop-app")
    assert fx["ops"]["respond"] == protocol.respond_op("perm1", "allow")
    assert fx["ops"]["quit"] == protocol.quit_op()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
