#!/usr/bin/env python3
"""Scripted Jaeger stack smoke verifier (API-level + ports + adapters).

Checks process/ports, HTTP health, profile list, session list, per-profile
tab API endpoints (sessions / models / gateway status), and best-effort
agent/bridge reachability. Live LLM tool-calls are gated behind --live
(expensive / unsafe for CI).

Usage:
  ./scripts/verify-stack-smoke.py
  ./scripts/verify-stack-smoke.py --start
  ./scripts/verify-stack-smoke.py --chat-url http://100.74.2.15:8790/ --start
  ./scripts/verify-stack-smoke.py --live   # also run live chat/tool verify

Exit code: 0 when all required checks PASS; non-zero on any FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Locked product topology
DEFAULT_CHAT_URL = "http://127.0.0.1:8790/"
TAILSCALE_CHAT_URL = "http://100.74.2.15:8790/"
HERMES_RUNTIME_PORT = 8787
CHAT_PORT = 8790
ADAPTERS = (
    ("jaeger", 8642, "Jaeger"),
    ("roundtable", 8643, "Roundtable"),
    ("openclaw", 8644, "OpenClaw"),
)
REQUIRED_PROFILES = {
    "default": "Hermes Agent",
    "jaeger": "Jaeger",
    "openclaw": "OpenClaw",
    "roundtable": "Roundtable",
}
PROFILE_COOKIE_IDS = ("default", "jaeger", "openclaw", "roundtable")

# Key UI tab endpoints discovered from vendor/hermes-webui/api/routes.py + static JS
TAB_ENDPOINTS = (
    ("sessions", "/api/sessions"),
    ("models", "/api/models"),
    ("gateway_status", "/api/gateway/status"),
    ("health_agent", "/api/health/agent"),
    ("profile_active", "/api/profile/active"),
    ("settings", "/api/settings"),
    ("skills", "/api/skills"),
    ("memory", "/api/memory"),
    ("workspaces", "/api/workspaces"),
    ("crons", "/api/crons"),
    ("insights", "/api/insights"),
    ("auth_status", "/api/auth/status"),
)

ADAPTER_LAUNCHD = {
    8642: "com.jenkinsrobotics.jaeger-hermes-adapter",
    8643: "com.jenkinsrobotics.roundtable-hermes-adapter",
    8644: "com.jenkinsrobotics.openclaw-hermes-adapter",
}

CHECKLIST_PATH = REPO_ROOT / "scripts" / "verify-stack-ui-checklist.md"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass
class Matrix:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", *, required: bool = True) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail, required=required))

    @property
    def failed_required(self) -> list[Check]:
        return [c for c in self.checks if c.required and not c.ok]

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.ok)

    def print_matrix(self) -> None:
        width = max((len(c.name) for c in self.checks), default=10)
        print("\n=== STACK SMOKE MATRIX ===")
        for c in self.checks:
            mark = "PASS" if c.ok else ("FAIL" if c.required else "WARN")
            req = "req" if c.required else "opt"
            detail = f" — {c.detail}" if c.detail else ""
            print(f"  [{mark}] ({req}) {c.name:<{width}}{detail}")
        print(
            f"\nSummary: {self.passed} passed, {self.failed} failed "
            f"({len(self.failed_required)} required failures)"
        )


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    profile: str | None = None,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, str]:
    hdrs = {"Accept": "application/json", "User-Agent": "jaeger-stack-smoke/1.0"}
    if headers:
        hdrs.update(headers)
    if profile:
        hdrs["Cookie"] = f"hermes_profile={profile}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
        method = method if method != "GET" else "POST"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = raw
            return status, payload, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload, str(exc)
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)


def _jaeger_bin() -> list[str]:
    local = REPO_ROOT / "jaeger"
    if local.is_file():
        return [str(local)]
    return ["jaeger"]


def _python() -> str:
    venv = REPO_ROOT / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    return sys.executable


def ensure_started(matrix: Matrix, *, start_runtime: bool) -> None:
    """Start adapters + chat WebUI (+ optional Hermes runtime) if missing."""
    domain = f"gui/{os.getuid()}"
    for _name, port, label in ADAPTERS:
        if _port_open(port):
            matrix.add(f"start.skip_adapter_{port}", True, f"{label} :{port} already up")
            continue
        plist_label = ADAPTER_LAUNCHD[port]
        print(f"  Starting adapter {label} ({plist_label})...")
        # Prefer kickstart of loaded job; fall back to bootstrap from LaunchAgents.
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", f"{domain}/{plist_label}"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            plist = Path.home() / "Library/LaunchAgents" / f"{plist_label}.plist"
            if plist.is_file():
                subprocess.run(
                    ["launchctl", "bootstrap", domain, str(plist)],
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["launchctl", "kickstart", f"{domain}/{plist_label}"],
                    capture_output=True,
                    text=True,
                )
        ready = False
        for _ in range(50):
            if _port_open(port):
                ready = True
                break
            time.sleep(0.2)
        matrix.add(
            f"start.adapter_{port}",
            ready,
            f"{label} :{port} {'ready' if ready else 'not listening'}",
        )

    # Jaeger bridge (Unix socket) — needed for Tasks/crons scheduler forward.
    bridge_label = "com.jenkinsrobotics.jaeger-bridge"
    print("  Ensuring Jaeger Bridge (launchd)...")
    r = subprocess.run(
        ["launchctl", "kickstart", "-k", f"{domain}/{bridge_label}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        plist = Path.home() / "Library/LaunchAgents" / f"{bridge_label}.plist"
        if plist.is_file():
            subprocess.run(
                ["launchctl", "bootstrap", domain, str(plist)],
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["launchctl", "kickstart", f"{domain}/{bridge_label}"],
                capture_output=True,
                text=True,
            )
            time.sleep(1.0)
            matrix.add("start.jaeger_bridge", True, "bootstrap+kickstart attempted", required=False)
        else:
            matrix.add("start.jaeger_bridge", False, "plist missing", required=False)
    else:
        time.sleep(0.5)
        matrix.add("start.jaeger_bridge", True, "kickstart ok", required=False)

    if not _port_open(CHAT_PORT):
        print("  Starting Jaeger WebUI (chat face :8790)...")
        r = subprocess.run(
            _jaeger_bin() + ["webui", "start"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        ready = False
        for _ in range(60):
            if _port_open(CHAT_PORT):
                ready = True
                break
            time.sleep(0.25)
        detail = (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
        matrix.add(
            "start.webui_8790",
            ready,
            f"{'ready' if ready else 'failed'}; {detail[0][:120]}",
        )
    else:
        matrix.add("start.skip_webui_8790", True, "chat :8790 already up")

    if start_runtime and not _port_open(HERMES_RUNTIME_PORT):
        print("  Starting Hermes runtime container (:8787; not a chat bookmark)...")
        r = subprocess.run(
            _jaeger_bin() + ["webui", "start", "--container"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        ready = False
        for _ in range(80):
            if _port_open(HERMES_RUNTIME_PORT):
                ready = True
                break
            time.sleep(0.25)
        # Runtime may publish only on Tailscale; also accept container health via service.
        if not ready:
            try:
                sys.path.insert(0, str(REPO_ROOT))
                from jaeger_ai.features.hermes_webui import HermesWebUIService

                st = HermesWebUIService().status()
                ready = bool((st.get("container") or {}).get("state") == "running")
            except Exception as exc:  # noqa: BLE001
                detail_extra = str(exc)
            else:
                detail_extra = "container state running"
        else:
            detail_extra = "port open"
        matrix.add(
            "start.hermes_runtime_8787",
            ready,
            detail_extra,
            required=False,  # chat face can work without container UI
        )
    elif _port_open(HERMES_RUNTIME_PORT):
        matrix.add("start.skip_hermes_runtime", True, ":8787 already up", required=False)


def check_ports(matrix: Matrix) -> None:
    matrix.add("port.8790_chat", _port_open(CHAT_PORT), "Jaeger WebUI chat face")
    # Hermes runtime is topology-locked but not the chat bookmark.
    # Often published on Tailscale only (100.74.2.15), not loopback.
    runtime_up = _port_open(HERMES_RUNTIME_PORT) or _port_open(HERMES_RUNTIME_PORT, "100.74.2.15")
    where = "127.0.0.1" if _port_open(HERMES_RUNTIME_PORT) else (
        "100.74.2.15" if _port_open(HERMES_RUNTIME_PORT, "100.74.2.15") else "down"
    )
    matrix.add(
        "port.8787_hermes_runtime",
        runtime_up,
        f"Hermes runtime (NOT a chat bookmark) via {where}",
        required=False,
    )
    for name, port, label in ADAPTERS:
        matrix.add(f"port.{port}_{name}", _port_open(port), f"{label} adapter")


def check_http_health(matrix: Matrix, chat_url: str) -> None:
    base = chat_url.rstrip("/")
    # Root HTML
    status, payload, err = _http(base + "/", timeout=10)
    ok = 200 <= status < 400 or status in {401, 403}  # auth gate still means up
    # Prefer a real API health
    st2, body2, err2 = _http(base + "/api/auth/status", timeout=10)
    if 200 <= st2 < 500:
        ok = True
        status, payload, err = st2, body2, err2
    matrix.add(
        "http.chat_face",
        ok,
        f"{base}/ -> HTTP {status}" + (f" ({err})" if err and not ok else ""),
    )

    # Optional Tailscale face
    if "127.0.0.1" in base or "localhost" in base:
        ts = TAILSCALE_CHAT_URL.rstrip("/")
        st, _, e = _http(ts + "/api/auth/status", timeout=5)
        matrix.add(
            "http.chat_face_tailscale",
            200 <= st < 500,
            f"{ts} -> HTTP {st}" + (f" ({e})" if e and st == 0 else ""),
            required=False,
        )

    for name, port, label in ADAPTERS:
        url = f"http://127.0.0.1:{port}/health"
        st, body, e = _http(url, timeout=5)
        if st == 0 or st == 404:
            st2, body2, e2 = _http(f"http://127.0.0.1:{port}/v1/health", timeout=5)
            if st2:
                st, body, e = st2, body2, e2
        ok = 200 <= st < 400
        detail = f"HTTP {st}"
        if isinstance(body, dict):
            detail += f" keys={sorted(body.keys())[:6]}"
        if e and not ok:
            detail += f" ({e})"
        matrix.add(f"http.adapter_{name}_health", ok, detail)


def _profile_names_from_payload(payload: Any) -> dict[str, str]:
    """Map profile id -> display name from /api/profiles response."""
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("profiles") or payload.get("items") or payload.get("data") or []
        if not rows and "name" in payload:
            rows = [payload]
    else:
        rows = []
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("id") or "").strip()
        if not name:
            continue
        display = (
            row.get("display_name")
            or row.get("displayName")
            or row.get("label")
            or row.get("title")
            or name
        )
        out[name] = str(display)
    return out


def check_profiles_and_sessions(matrix: Matrix, chat_url: str) -> dict[str, str]:
    base = chat_url.rstrip("/")
    st, payload, err = _http(base + "/api/profiles", profile="default", timeout=30)
    ok = 200 <= st < 300 and payload is not None
    names = _profile_names_from_payload(payload) if ok else {}
    matrix.add(
        "api.profiles",
        ok,
        f"HTTP {st}; {len(names)} profiles" + (f" ({err})" if err and not ok else ""),
    )
    # Apply canonical display-name expectations (API may return raw id).
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from jaeger_ai.features.hermes_webui.profile_layout import PROFILE_DISPLAY_NAMES

        expected_labels = dict(PROFILE_DISPLAY_NAMES)
    except Exception:
        expected_labels = dict(REQUIRED_PROFILES)

    for pid, expected in REQUIRED_PROFILES.items():
        present = pid in names or any(n.lower() == pid for n in names)
        # display may be raw name; compare against expected friendly label when present
        actual = names.get(pid) or names.get(pid.capitalize()) or ""
        expected_label = expected_labels.get(pid, expected)
        label_ok = True
        if actual and actual != pid:
            label_ok = actual == expected or actual.lower() == expected.lower()
        # /api/profiles may omit display_name; friendly label comes from profile_layout.
        detail = (
            f"id={pid} api_name={actual or '?'} expected_display={expected_label}"
        )
        matrix.add(f"api.profile_present.{pid}", present and label_ok, detail)

    st, payload, err = _http(base + "/api/sessions", profile="default", timeout=30)
    ok = 200 <= st < 300
    count = 0
    if isinstance(payload, dict):
        sessions = payload.get("sessions") or payload.get("items") or payload.get("data") or []
        if isinstance(sessions, list):
            count = len(sessions)
    elif isinstance(payload, list):
        count = len(payload)
    matrix.add(
        "api.sessions",
        ok,
        f"HTTP {st}; ~{count} sessions" + (f" ({err})" if err and not ok else ""),
    )
    return names


def check_per_profile_tabs(matrix: Matrix, chat_url: str) -> None:
    base = chat_url.rstrip("/")
    for profile in PROFILE_COOKIE_IDS:
        # Switch profile (documented equivalent: POST /api/profile/switch)
        st, payload, err = _http(
            base + "/api/profile/switch",
            method="POST",
            body={"name": profile},
            profile=profile,
            timeout=30,
        )
        # Some builds return 200 with cookie; others may 204/200 with {ok:true}
        switch_ok = 200 <= st < 300
        if not switch_ok and st in {400, 404, 405}:
            # Fallback: cookie-only profile scoping (no explicit switch endpoint success)
            st2, _, _ = _http(base + "/api/profile/active", profile=profile, timeout=15)
            switch_ok = 200 <= st2 < 300
            detail = f"switch HTTP {st}; cookie-active fallback HTTP {st2}"
        else:
            detail = f"HTTP {st}"
            if isinstance(payload, dict):
                detail += f" active={payload.get('active') or payload.get('profile') or payload.get('name')}"
            if err and not switch_ok:
                detail += f" ({err})"
        matrix.add(f"api.profile_switch.{profile}", switch_ok, detail)

        for ep_name, path in TAB_ENDPOINTS:
            st, payload, err = _http(base + path, profile=profile, timeout=45)
            ok = 200 <= st < 300
            required = True
            # Some endpoints legitimately 401 when auth required — still "reachable"
            if st in {401, 403} and ep_name in {"settings", "memory"}:
                ok = True
            detail = f"HTTP {st}"
            # Tasks/crons often forward through the Jaeger bridge/runner. A 503
            # "scheduler unavailable" / "bridge is not listening" is a soft
            # dependency — warn, don't fail the chat-face smoke.
            if ep_name == "crons" and st == 503:
                body_s = ""
                if isinstance(payload, dict):
                    body_s = str(payload.get("error") or payload)
                elif isinstance(payload, str):
                    body_s = payload
                if any(
                    token in body_s.lower()
                    for token in ("scheduler unavailable", "bridge is not listening", "runner returned")
                ):
                    ok = False
                    required = False
                    detail += f" soft-dep: {body_s[:160]}"
            if err and not ok and required:
                detail += f" ({err})"
            matrix.add(f"api.{profile}.{ep_name}", ok, detail, required=required)


def check_agent_reachability(matrix: Matrix, chat_url: str, *, live: bool) -> None:
    """Best-effort bridge/agent alive proofs without spending LLM tokens by default."""
    base = chat_url.rstrip("/")
    # WebUI agent health
    st, payload, err = _http(base + "/api/health/agent", profile="jaeger", timeout=20)
    ok = 200 <= st < 300
    detail = f"HTTP {st}"
    if isinstance(payload, dict):
        detail += f" keys={sorted(str(k) for k in payload.keys())[:8]}"
    if err and not ok:
        detail += f" ({err})"
    matrix.add("reach.webui_health_agent", ok, detail)

    # Adapter health already covered; also try jaeger CLI status snippet
    try:
        r = subprocess.run(
            _jaeger_bin() + ["status"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (r.stdout or "") + (r.stderr or "")
        has_web = "Web UI" in out
        matrix.add(
            "reach.jaeger_status",
            r.returncode == 0 or has_web,
            f"exit={r.returncode}; webui_line={'yes' if has_web else 'no'}",
            required=False,
        )
    except Exception as exc:  # noqa: BLE001
        matrix.add("reach.jaeger_status", False, str(exc), required=False)

    if not live:
        matrix.add(
            "reach.live_llm_toolcall",
            True,
            "SKIPPED (pass --live to run scripts/verify-agent-webui.py / verify-native-webui.py)",
            required=False,
        )
        return

    # Live path: reuse existing opt-in scripts (creates sessions; uses model tokens)
    agent_script = REPO_ROOT / "scripts" / "verify-agent-webui.py"
    native_script = REPO_ROOT / "scripts" / "verify-native-webui.py"
    if agent_script.is_file():
        print("  --live: running verify-agent-webui.py (uses model tokens)...")
        r = subprocess.run(
            [_python(), str(agent_script), "--url", base + "/"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
        matrix.add(
            "reach.live_agent_webui",
            r.returncode == 0,
            (r.stdout or r.stderr or "")[-300:].replace("\n", " | "),
        )
    else:
        matrix.add("reach.live_agent_webui", False, "script missing")

    if native_script.is_file():
        print("  --live: running verify-native-webui.py (uses model tokens; denies approvals)...")
        r = subprocess.run(
            [_python(), str(native_script), "--url", base + "/", "--profile", "jaeger"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
        matrix.add(
            "reach.live_native_tools",
            r.returncode == 0,
            (r.stdout or r.stderr or "")[-300:].replace("\n", " | "),
        )
    else:
        matrix.add("reach.live_native_tools", False, "script missing", required=False)


def print_ui_checklist_section() -> None:
    print("\n=== MANUAL UI CLICK CHECKLIST ===")
    print("Browser automation is not part of this smoke. Click through:")
    print(f"  Companion: {CHECKLIST_PATH}")
    if CHECKLIST_PATH.is_file():
        # Print a short digest of tabs
        print(
            "  Tabs per profile (Hermes Agent / Jaeger / OpenClaw / Roundtable):\n"
            "    Chat, Tasks, Kanban, Skills, Memory, Spaces, Agent profiles,\n"
            "    Todos, Insights, Logs, Settings — plus New chat, profile switch,\n"
            "    model/workspace chips, send, gateway restart (careful), YOLO pill."
        )
    else:
        print("  (checklist file missing — create scripts/verify-stack-ui-checklist.md)")


def resolve_chat_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url.rstrip("/") + "/"
    # Prefer Tailscale face when reachable; else loopback
    st, _, _ = _http(TAILSCALE_CHAT_URL.rstrip("/") + "/api/auth/status", timeout=3)
    if 200 <= st < 500:
        return TAILSCALE_CHAT_URL
    return DEFAULT_CHAT_URL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--chat-url",
        default=None,
        help="Chat face base URL (default: Tailscale :8790 if up, else 127.0.0.1:8790)",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start adapters + WebUI if ports are down (does not destroy data)",
    )
    parser.add_argument(
        "--start-runtime",
        action="store_true",
        help="With --start, also try starting Hermes runtime container (:8787)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run live LLM/chat/tool verifiers (uses model tokens; creates sessions)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary after the matrix",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")
    matrix = Matrix()
    print("Jaeger stack smoke verifier")
    print(f"  repo: {REPO_ROOT}")

    if args.start:
        print("\n--start: ensuring required services...")
        ensure_started(matrix, start_runtime=args.start_runtime)

    chat_url = resolve_chat_url(args.chat_url)
    print(f"  chat: {chat_url}")
    print(f"  hermes runtime port: {HERMES_RUNTIME_PORT} (not a chat bookmark)")

    check_ports(matrix)
    check_http_health(matrix, chat_url)
    check_profiles_and_sessions(matrix, chat_url)
    check_per_profile_tabs(matrix, chat_url)
    check_agent_reachability(matrix, chat_url, live=args.live)
    print_ui_checklist_section()
    matrix.print_matrix()

    if args.json:
        print(
            json.dumps(
                {
                    "chat_url": chat_url,
                    "passed": matrix.passed,
                    "failed": matrix.failed,
                    "required_failures": [c.name for c in matrix.failed_required],
                    "checks": [
                        {
                            "name": c.name,
                            "ok": c.ok,
                            "required": c.required,
                            "detail": c.detail,
                        }
                        for c in matrix.checks
                    ],
                },
                indent=2,
            )
        )

    return 1 if matrix.failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
