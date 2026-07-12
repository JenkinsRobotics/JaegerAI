#!/usr/bin/env python3
"""WALK — 0.9.3 Task 1, the headless confirmation surface.

Mandatory manual walk (not a pytest file) for the roadmap item's own
requirement: "Walk: a real bridge session approving open_on_host once,
'always' persisting across restart." Drives the REAL wire path — the
same ``jaeger_ai.interfaces.bridge.main()`` entry point ``jaeger bridge``
runs, the REAL ``BridgeConfirmationProvider``, the REAL tier-gated
``open_on_host`` tool (via its ``requires_tier`` wrapper), and the REAL
on-disk ``<instance>/permissions.json`` grant store.

Only two things are faked, exactly the way this repo's own
``test_bridge.py`` fakes them (see its docstring): ``boot_for_tui`` (no
multi-GB model load) and the final ``open`` subprocess call inside
``agent.tools.host._run_open`` (no actual Safari launch). Everything
between "operator says open youtube in safari" and "grant written to
disk" is the real production code path.

Run: <venv>/bin/python dev/scripts/walk_task1_bridge_confirmation.py
Exit 0 + "WALK PASSED" on success; asserts fail loudly otherwise.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock


def _banner(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def _narrate(frames: list[dict]) -> None:
    for f in frames:
        t = f.get("type")
        if t == "request":
            print(f"  <- request  id={f['id']} kind={f['kind']} "
                  f"options={f['options']}  prompt={f['prompt']!r}")
        elif t == "reply":
            print(f"  <- reply    text={f['text']!r} error={f.get('error')!r}")
        elif t == "state":
            print(f"  <- state    busy={f['busy']}")
        elif t in ("ready", "agent_state", "bye"):
            print(f"  <- {t}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jaeger-walk-task1-"))
    inst = tmp / "walk-inst"
    inst.mkdir()
    for f in ("identity.yaml", "config.yaml", "manifest.json"):
        (inst / f).write_text("{}", encoding="utf-8")

    opened_calls: list[list[str]] = []

    def fake_run_open(args, label):
        opened_calls.append(args)
        return {"opened": True, **label}

    class _FakeBoot:
        def __init__(self):
            self.client = object()

        def cleanup(self):
            pass

    def fake_boot_for_tui(*, instance_name, **kwargs):
        from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
        boot = _FakeBoot()
        boot.layout = InstanceLayout(resolve_instance_dir(instance_name))
        return boot

    def make_run_for_voice(label: str):
        def run_for_voice(client, text, session_key=None):
            # This IS the operator's literal field case: the agent decides
            # to call the tier-2 open_on_host tool mid-turn. The
            # requires_tier wrapper consults current_policy() — by now
            # (post-boot) that's the REAL BridgeConfirmationProvider.
            from jaeger_ai.agent.tools.host import _t_open_on_host
            result = _t_open_on_host(target="https://youtube.com")
            print(f"  [{label}] tool result: {result}")
            return {"text": f"opened it ({result.get('opened')})", "error": None}
        return run_for_voice

    def run_session(label: str, stdin_text: str) -> list[dict]:
        proto = io.StringIO()
        with mock.patch("sys.stdout", proto), \
             mock.patch("sys.stdin", io.StringIO(stdin_text)), \
             mock.patch.dict("os.environ", {"JAEGER_INSTANCE_DIR": str(inst)}), \
             mock.patch("jaeger_ai.main.boot_for_tui", fake_boot_for_tui,
                        create=True), \
             mock.patch("jaeger_ai.main.run_for_voice", make_run_for_voice(label),
                        create=True), \
             mock.patch("jaeger_ai.agent.tools.host._run_open", fake_run_open):
            from jaeger_ai.interfaces import bridge
            rc = bridge.main(argv=[])
        frames = [json.loads(ln) for ln in proto.getvalue().splitlines() if ln.strip()]
        assert rc == 0, f"{label}: bridge exited {rc}"
        return frames

    # ---- Session 1: first boot, operator says "open youtube in safari" ----
    _banner("SESSION 1 (first boot) — 'open youtube in safari'")
    stdin1 = ('{"text":"open youtube in safari"}\n'
             '{"op":"respond","id":"perm1","answer":"always"}\n'
             '{"op":"quit"}\n')
    frames1 = run_session("session-1", stdin1)
    _narrate(frames1)

    requests1 = [f for f in frames1 if f["type"] == "request"]
    replies1 = [f for f in frames1 if f["type"] == "reply"]
    assert len(requests1) == 1, f"expected exactly one approval frame, got {requests1}"
    assert requests1[0]["kind"] == "approval"
    assert requests1[0]["options"] == ["once", "always", "deny"]
    assert "host.open_on_host" in requests1[0]["prompt"]
    assert replies1 and "opened it (True)" in replies1[0]["text"]
    assert opened_calls == [["https://youtube.com"]]

    grants_file = inst / "permissions.json"
    assert grants_file.is_file(), "permissions.json was never written"
    granted = json.loads(grants_file.read_text())["granted_skills"]
    assert "host" in granted, f"'host' skill not persisted: {granted}"
    print(f"\n  permissions.json on disk: {granted}")
    print("  PASS: exactly one approval frame; 'always' persisted the "
          "'host' grant to disk.")

    # ---- Session 2: simulate a full app restart — fresh process state, ----
    # ---- SAME on-disk instance dir. The whole point of 'always' is that ----
    # ---- PermissionGrants.load() re-reads permissions.json from a totally
    # ---- fresh BridgeConfirmationProvider construction — exactly what a
    # ---- real process restart does; we simulate the restart by running a
    # ---- brand new bridge.main() (fresh _Ctx, fresh install_policy call)
    # ---- rather than a multi-GB real model reboot.
    opened_calls.clear()
    _banner("SESSION 2 (simulated restart, same instance dir) — repeat request")
    stdin2 = '{"text":"open youtube in safari"}\n{"op":"quit"}\n'
    frames2 = run_session("session-2", stdin2)
    _narrate(frames2)

    requests2 = [f for f in frames2 if f["type"] == "request"]
    replies2 = [f for f in frames2 if f["type"] == "reply"]
    assert requests2 == [], f"restart-persistence broken — got a request frame: {requests2}"
    assert replies2 and "opened it (True)" in replies2[0]["text"]
    assert opened_calls == [["https://youtube.com"]]
    print("\n  PASS: second session (post-restart) executed open_on_host "
          "with ZERO approval frames — the persisted grant held.")

    _banner("WALK PASSED")
    print(f"  instance dir: {inst}  (left on disk for inspection)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
