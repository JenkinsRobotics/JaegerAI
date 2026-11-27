"""What the Swift Mac shell does natively, for the NexusUI app (INVENTORY.md maps each Swift element here).

Everything is a plain function or a small monitor thread; the screen calls them through serve.py's /shell routes and
the native menu-bar item (native.py) calls the same ones, so the window, a browser tab and the menu stay in step.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from .gateway import Gateway

WEBUI = (os.environ.get('JAEGER_SHELL_WEBUI_URL') or 'http://127.0.0.1:8790').rstrip('/')
STATE = Path(os.environ.get('JAEGER_STATE_DIR') or Path.home() / '.jaeger').expanduser()
SETTINGS = STATE / 'nexus-ui.json'   # pause, hotkey, history consent (Swift keeps these in UserDefaults)
LOGIN_PLIST = Path.home() / 'Library/LaunchAgents/com.jenkinsrobotics.JaegerAI.nexus.plist'
CLIP_MAX = 100_000   # ClipboardPreview.maxBytes
PANES = {   # ComputerSettingsTarget + DroidMenuController's permission items
    'microphone': 'Privacy_Microphone', 'camera': 'Privacy_Camera',
    'accessibility': 'Privacy_Accessibility', 'screen_recording': 'Privacy_ScreenCapture',
}


# ── settings (Shell Pause, hotkey, history consent) ────────────────────────────

def load() -> dict:
    s = {'paused': False, 'hotkey': 'ctrl-opt-j', 'history_app_names': False}
    try:
        s.update(json.loads(SETTINGS.read_text()))
    except (OSError, ValueError):
        pass
    return s


def save(**changes) -> dict:
    s = {**load(), **changes}
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2))
    return s


# ── deep links (JaegerShellCore/JaegerDeepLink.swift, same rules) ─────────────

_ID = re.compile(r'[A-Za-z0-9._:-]{1,256}')


def deep_link(url: str) -> dict | None:
    """jaeger://notifications -> inbox; jaeger://conversation/<id> -> that chat. Anything else is refused."""
    from urllib.parse import unquote, urlsplit
    try:
        p = urlsplit(url or '')
        port = p.port
    except ValueError:
        return None
    if p.scheme.lower() != 'jaeger' or p.username or p.password or port or p.query or p.fragment or '?' in url or '#' in url:
        return None
    host = (p.hostname or '').lower()
    if host == 'notifications':
        return {'target': 'notifications'} if p.path in ('', '/') else None
    if host == 'conversation':
        parts = p.path.split('/')
        sid = unquote(parts[1]) if len(parts) == 2 and not parts[0] else ''
        if sid not in ('.', '..') and _ID.fullmatch(sid):
            return {'target': 'conversation', 'session_id': sid}
    return None


# ── probes and monitors ───────────────────────────────────────────────────────

def webui_up() -> bool:
    try:
        with urllib.request.urlopen(WEBUI + '/', timeout=2) as r:  # noqa: S310 (loopback)
            return r.status < 400
    except OSError:
        return False


class Monitors:
    """StatusItemController's 10 s health timer, LiveTaskMonitor's 1.5 s poll and its notifications."""

    def __init__(self, gw: Gateway, on_change=None):
        self.gw, self.on_change = gw, on_change or (lambda: None)
        self.health: dict = {}
        self.webui = False
        self.tasks: dict = {'state': 'unknown', 'running': [], 'recent': []}
        self.droid: dict = {}
        self._told: dict[str, float] = {}

    def start(self):
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._task_loop, daemon=True).start()
        return self

    def _health_loop(self):
        while True:
            st, h = self.gw.call('GET', '/health', timeout=3)
            self.health = h if st == 200 else {}
            self.webui = webui_up()
            if self.health:
                st, d = self.gw.call('GET', '/v1/droid/status', timeout=2.5)
                self.droid = d if st == 200 else {'error': d.get('error') or f'HTTP {st}'}
            else:
                self.droid = {}
            self.on_change()
            time.sleep(10)

    def _task_loop(self):
        while True:
            st, j = self.gw.call('GET', '/v1/live/tasks', timeout=3)
            if st in (404, 405, 410, 501):   # Swift stops polling for good on an unsupported route
                self.tasks = {'state': 'unsupported', 'running': [], 'recent': []}
                self.on_change()
                return
            if st == 200:
                self.tasks = {'state': 'ok', 'running': j.get('running') or [], 'recent': (j.get('recent') or [])[:3]}
                self._notify(self.tasks)
                self.on_change()
            time.sleep(1.5)

    def _notify(self, t: dict):
        now = time.time()
        for task in t['running']:
            rid = task.get('request_id', '')
            if task.get('background') or (task.get('elapsed_s') or 0) < 8 or now - self._told.get(rid, 0) < 3:
                continue
            self._told[rid] = now
            notify(f"Working: {task.get('title', 'Jaeger task')}", task.get('step', ''))
        for task in t['recent']:
            rid = task.get('request_id', '')
            if rid in self._told and self._told[rid] > 0:
                ok = task.get('status') != 'failed'
                notify(f"{'Done' if ok else 'Failed'}: {task.get('title', 'Jaeger task')}", task.get('result', '')[:200], sound=True)
                self._told[rid] = -1

    def gateway_text(self) -> str:
        h = self.health
        if not h:
            return 'Gateway: offline (127.0.0.1:33418)'
        return f"Gateway: {h.get('status', 'ok')} · up {int(h.get('uptime_s') or 0)} s (127.0.0.1:33418)"

    def droid_lines(self) -> list[str]:
        d = self.droid
        if not self.health:
            return ['Droid: Gateway offline']
        if 'error' in d:
            return [f"Droid: unavailable ({d['error']})"]
        awake = bool(d.get('awake'))
        cam = {'streaming': 'Streaming', 'parked': 'Camera Parked', 'ready': 'Camera Ready'}.get(str(d.get('camera')), str(d.get('camera') or 'camera unknown'))
        line = f"Droid: {'Awake' if awake else 'Asleep'} ({cam})" + (' · E-Stop ON' if d.get('estop_latched') else '')
        pose, cams = d.get('pose') or {}, ((d.get('devices') or {}).get('cameras') or [])
        gimbal = next((c['name'] for c in cams if c.get('gimbal_capable')), None)
        sense = f"{gimbal} · pan {pose.get('pan_deg', 0):g}° · tilt {pose.get('tilt_deg', 0):g}°" if gimbal else ''
        return [line] + ([sense] if sense else [])


# ── actions (menu items) ──────────────────────────────────────────────────────

def notify(title: str, body: str = '', sound: bool = False):
    """A macOS notification. ponytail: osascript, so clicks open Script Editor's notice, not a chat; a bundle-signed
    UNUserNotificationCenter sender would route clicks like the Swift app does."""
    esc = lambda s: s.replace('\\', '\\\\').replace('"', '\\"')
    script = f'display notification "{esc(body)}" with title "Jaeger" subtitle "{esc(title)}"' + (' sound name "Glass"' if sound else '')
    subprocess.run(['osascript', '-e', script], check=False, capture_output=True)


def open_pane(which: str):
    pane = PANES[which]
    subprocess.run(['open', f'x-apple.systempreferences:com.apple.preference.security?{pane}'], check=False)


def stack(verb: str) -> dict:
    """Start / Restart / Stop the Jaeger stack: the same `jaeger stack <up|restart|down> --json` the Swift app runs."""
    r = subprocess.run([sys.executable, '-B', '-m', 'jaeger_ai', 'stack', verb, '--json'],
                       capture_output=True, text=True, timeout=90)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': r.returncode == 0, 'output': (r.stdout + r.stderr)[-400:]}


def login_item(on: bool | None = None) -> bool:
    """Launch at Login, opt-in only: a LaunchAgent that opens this app (Swift uses SMAppService.mainApp)."""
    if on is None:
        return LOGIN_PLIST.exists()
    uid = os.getuid()
    if on:
        LOGIN_PLIST.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_PLIST.write_bytes(plistlib.dumps({
            'Label': LOGIN_PLIST.stem, 'RunAtLoad': True,
            'ProgramArguments': [sys.executable, '-B', '-m', 'jaeger_ai.interfaces.nexus'],
            'WorkingDirectory': str(Path(__file__).resolve().parents[3]),
            'EnvironmentVariables': {k: v for k, v in os.environ.items() if k.startswith('JAEGER_')},
        }))
    else:
        subprocess.run(['launchctl', 'bootout', f'gui/{uid}', str(LOGIN_PLIST)], check=False, capture_output=True)
        LOGIN_PLIST.unlink(missing_ok=True)
    return LOGIN_PLIST.exists()


def lock_mac():
    """MacControlMenuController: SACLockScreenImmediate, falling back to sleeping the display."""
    try:
        import ctypes
        lib = ctypes.CDLL('/System/Library/PrivateFrameworks/login.framework/Versions/Current/login')
        if lib.SACLockScreenImmediate() == 0:
            return
    except (OSError, AttributeError):
        pass
    display_off()


def display_off():
    subprocess.run(['pmset', 'displaysleepnow'], check=False)


def mac_status() -> dict:
    """Mac Status…: uptime, disk free and battery."""
    boot = subprocess.run(['sysctl', '-n', 'kern.boottime'], capture_output=True, text=True).stdout
    m = re.search(r'sec = (\d+)', boot)
    up = int(time.time() - int(m.group(1))) if m else 0
    du = shutil.disk_usage('/')
    batt = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True).stdout
    b = re.search(r'(\d+)%;\s*([^;]+)', batt)
    return {'uptime': f'{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m',
            'disk_free': f'{du.free / 1e9:.0f} GB of {du.total / 1e9:.0f} GB',
            'battery': f'{b.group(1)}% ({b.group(2).strip()})' if b else 'no battery'}


def clipboard_read() -> dict:
    """ClipboardPreview.project: text only after an explicit read, refused above 100 kB."""
    r = subprocess.run(['pbpaste'], capture_output=True)
    if r.returncode or not r.stdout:
        return {'state': 'no_text_or_access_unavailable', 'max_bytes': CLIP_MAX}
    if len(r.stdout) > CLIP_MAX:
        return {'state': 'over_limit', 'max_bytes': CLIP_MAX}
    return {'state': 'text_available', 'text': r.stdout.decode('utf-8', 'replace'), 'max_bytes': CLIP_MAX, 'content_type': 'text/plain'}


def clipboard_write(text: str):
    subprocess.run(['pbcopy'], input=text.encode(), check=True)


def permissions() -> dict:
    """Microphone / camera (the Droid menu's Permissions submenu), plus Accessibility and Screen Recording
    (computer.status) from jaeger_macos.probe_tcc_status. Reads only; never prompts."""
    names = {0: 'Not asked', 1: 'Restricted', 2: 'Denied', 3: 'Allowed'}
    out = {'microphone': 'unknown', 'camera': 'unknown'}
    try:   # AVFoundation loaded straight from the system: no pyobjc-framework-AVFoundation needed
        import objc
        objc.loadBundle('AVFoundation', {}, bundle_path='/System/Library/Frameworks/AVFoundation.framework')
        dev = objc.lookUpClass('AVCaptureDevice')
        out = {'microphone': names.get(dev.authorizationStatusForMediaType_('soun'), '?'),   # AVMediaTypeAudio
               'camera': names.get(dev.authorizationStatusForMediaType_('vide'), '?')}       # AVMediaTypeVideo
    except Exception:  # noqa: BLE001 — not macOS or no PyObjC: say unknown
        pass
    try:
        from jaeger_macos.tcc import probe_tcc_status
        for k, v in probe_tcc_status().items():
            out[k] = 'unknown' if v is None else ('Allowed' if v else 'Not allowed')
    except ImportError:
        pass
    return out


class Actions:
    """Every menu item of the Swift shell, by name. The window (pywebview) is passed in when there is one."""

    def __init__(self, gw: Gateway, mon: Monitors, bridge=None):
        self.gw, self.mon, self.bridge, self.window, self.shown = gw, mon, bridge, None, True
        self.on_pause = lambda paused: None

    def _show(self, on: bool):
        if self.window:
            self.window.show() if on else self.window.hide()
            self.shown = on

    def _droid(self, method, path, body=None):
        st, j = self.gw.call(method, path, body, timeout=10)
        if st not in (200, 202):
            raise RuntimeError(j.get('error') or f'Gateway said HTTP {st}')
        return j

    def run(self, name: str, arg=None):
        a = {
            'window.toggle': lambda: self._show(not self.shown),
            'window.show': lambda: self._show(True),
            'window.pin': lambda: self.window and setattr(self.window, 'on_top', bool(arg)),
            'shell.pause': lambda: self._pause(not load()['paused']),
            'stack.start': lambda: stack('up'), 'stack.restart': lambda: stack('restart'), 'stack.stop': lambda: stack('down'),
            'login.toggle': lambda: login_item(not login_item()),
            'open.browser': lambda: webbrowser.open(WEBUI + '/'),
            'open.droid': lambda: webbrowser.open(WEBUI + '/droid'),
            'droid.wake': lambda: self._droid('POST', '/v1/droid/wake', {'reason': 'nexusui_menubar'}),
            'droid.sleep': lambda: self._droid('POST', '/v1/droid/sleep', {'reason': 'nexusui_menubar'}),
            'droid.park': lambda: self._droid('POST', '/v1/droid/sleep', {'reason': 'nexusui_menubar_park'}),
            'droid.center': lambda: self._droid('POST', '/v1/embodiment/droid/act', {'action': 'center'}),
            'droid.refresh': lambda: self._droid('GET', '/v1/droid/devices?refresh=1'),
            'mac.lock': lock_mac, 'mac.display_off': display_off, 'mac.status': mac_status,
            'settings.open': lambda: open_pane(str(arg)),
            'notify.test': lambda: notify('Test notification', 'Notifications from the NexusUI app work.'),
            'clipboard.read': clipboard_read, 'clipboard.write': lambda: clipboard_write(str(arg or '')),
            'history.consent': lambda: save(history_app_names=bool(arg)),
            'hotkey.set': lambda: save(hotkey=str(arg)),
        }.get(name)
        if a is None:
            raise ValueError(f'no such action: {name}')
        out = a()
        self.mon.on_change()
        return out if isinstance(out, (dict, list, str, bool)) else True

    def _pause(self, paused: bool):
        save(paused=paused)
        self.on_pause(paused)
        return {'paused': paused}

    def status(self) -> dict:
        """Everything the status-item menu shows, for the screen's Shell tab."""
        s = load()
        return {'gateway': self.mon.gateway_text(), 'gateway_up': bool(self.mon.health),
                'webui': f"Main screen: {'running' if self.mon.webui else 'not running'} ({WEBUI.split('//')[1]})",
                'shell': 'Shell: paused (hotkey off)' if s['paused'] else 'Shell: active',
                'paused': s['paused'], 'hotkey': s['hotkey'], 'history_app_names': s['history_app_names'],
                'login': login_item(), 'tasks': self.mon.tasks, 'droid': self.mon.droid_lines(),
                'droid_raw': self.mon.droid, 'permissions': permissions()}


if __name__ == '__main__':   # self-check: deep-link rules match JaegerDeepLinkTests' cases
    assert deep_link('jaeger://conversation/agent-native%3Abuilder') == {'target': 'conversation', 'session_id': 'agent-native:builder'}
    assert deep_link('jaeger://notifications') == {'target': 'notifications'}
    for bad in ('https://example.com/conversation/owned', 'file:///owned', 'jaeger://conversation/owned?run=tool',
                'jaeger://conversation/owned#approve', 'jaeger://user:secret@conversation/owned', 'jaeger://conversation:80/owned',
                'jaeger://conversation/owned/extra', 'jaeger://conversation/..', 'jaeger://conversation/%2Fother',
                'jaeger://conversation/%252Fother', 'jaeger://conversation/owned%0Aother', 'jaeger://notifications/extra',
                'jaeger://run/owned', 'jaeger://conversation/', 'jaeger://conversation/' + 'x' * 257):
        assert deep_link(bad) is None, bad
    print('shell self-check ok')
