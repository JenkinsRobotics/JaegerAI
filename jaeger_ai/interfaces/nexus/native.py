"""The NexusUI app's native macOS parts (PyObjC, already there with pywebview): the menu-bar item with the Swift
shell's menus (StatusItemController, DroidMenuController, MacControlMenuController) and the global hotkey.

Runs inside pywebview's Cocoa app; install() is called on the main thread. The menu is rebuilt each time it opens,
from the same shell.Actions the screen's Shell tab uses.
"""
from __future__ import annotations

import threading

import AppKit
import objc
from PyObjCTools import AppHelper

from . import shell

KEYS = {'space': 49, 'j': 38, 'k': 40, 'return': 36}
MODS = {'ctrl': AppKit.NSEventModifierFlagControl, 'opt': AppKit.NSEventModifierFlagOption,
        'cmd': AppKit.NSEventModifierFlagCommand, 'shift': AppKit.NSEventModifierFlagShift}
DEVICE_MODS = MODS['ctrl'] | MODS['opt'] | MODS['cmd'] | MODS['shift']


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl-opt-j' -> (keyCode, modifier mask). Same spelling as the Swift app's JaegerHotkey plist key."""
    *mods, key = spec.lower().split('-')
    mask = 0
    for m in mods:
        mask |= MODS[m]
    return KEYS[key], mask


def alert(title: str, text: str, buttons=('OK',)) -> int:
    a = AppKit.NSAlert.alloc().init()
    a.setMessageText_(title); a.setInformativeText_(text)
    for b in buttons:
        a.addButtonWithTitle_(b)
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    return int(a.runModal()) - AppKit.NSAlertFirstButtonReturn


class Menu(AppKit.NSObject):
    """The status item and its menu; every item calls Actions.run(name, arg) off the main thread."""

    def initWithActions_quit_pill_(self, actions, quit_app, pill):
        self = objc.super(Menu, self).init()
        self.actions, self.quit_app, self.pill = actions, quit_app, pill
        self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        btn = self.item.button()
        btn.setTarget_(self); btn.setAction_('clicked:')
        btn.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)
        self.menu = AppKit.NSMenu.alloc().init(); self.menu.setDelegate_(self); self.menu.setAutoenablesItems_(False)
        self.handlers = {}
        self.refresh()
        return self

    # ── icon (StatusItemController: running/off icon, tasks ring, tooltip) ──
    @objc.python_method
    def refresh(self):
        st = self.actions.status()
        running = len(st['tasks']['running'])
        sym = 'circle.hexagongrid.fill' if st['gateway_up'] else 'circle.hexagongrid'
        if running:
            sym = 'arrow.triangle.2.circlepath'
        img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(sym, 'Jaeger')
        if img is not None:
            img.setTemplate_(True); self.item.button().setImage_(img)
        else:
            self.item.button().setTitle_('J')
        tip = 'Jaeger (NexusUI)' + (' — paused' if st['paused'] else '') + (f' — {running} tasks running' if running else '') \
            + ('' if st['gateway_up'] else ' — Offline')
        self.item.button().setToolTip_(tip)

    def clicked_(self, sender):
        ev = AppKit.NSApp.currentEvent()
        if ev is not None and (ev.type() == AppKit.NSEventTypeRightMouseUp or ev.modifierFlags() & MODS['ctrl']):
            self.item.popUpStatusItemMenu_(self.menu)   # right-click or ⌃-click: the menu
        else:
            self.run('window.toggle')                   # left click: show / hide the window

    # ── the menu, rebuilt when it opens ──
    def menuNeedsUpdate_(self, menu):
        st = self.actions.status()
        menu.removeAllItems(); self.handlers = {}
        add, sep = self._add, lambda: menu.addItem_(AppKit.NSMenuItem.separatorItem())
        add('Show / Hide Jaeger', 'window.toggle')
        add('Quick Ask…', lambda: self.pill())
        t = st['tasks']
        if t['state'] == 'unsupported':
            add('Tasks: not available (Gateway has no /v1/live/tasks)', None)
        else:
            add(f"Tasks running ({len(t['running'])})" if t['running'] else 'Tasks: none running', None)
            for x in t['running']:
                add(f"⟳ {x.get('title', 'task')} — {x.get('step', '')} ({int(x.get('elapsed_s') or 0)} s)", 'window.show')
            for x in t['recent']:
                add(f"{'✕' if x.get('status') == 'failed' else '✓'} {x.get('title', 'task')}", 'window.show')
        sep()
        add(st['webui'], None); add(st['gateway'], None); add(st['shell'], None)
        add('Resume Jaeger Shell' if st['paused'] else 'Pause Jaeger Shell', 'shell.pause')
        add('Start Jaeger stack…', ('stack.start', 'Start the Jaeger stack?'))
        add('Restart Jaeger stack…', ('stack.restart', 'Restart the Jaeger stack?'))
        add('Stop Jaeger stack…', ('stack.stop', 'Stop the Jaeger stack?'))
        add('Launch at Login', 'login.toggle', checked=st['login'])
        sep()
        d = st['droid_raw']
        for line in st['droid']:
            add(line, None)
        up, estop = st['gateway_up'], bool(d.get('estop_latched'))
        awake = bool(d.get('awake'))
        if awake:
            add('Turn Off Droid Mode (Sleep & Park)', 'droid.sleep', enabled=up)
        else:
            add('Turn On Droid Mode (Wake)', 'droid.wake', enabled=up and not estop)
        add('Park Camera Now (Privacy)', 'droid.park', enabled=up)
        add('Center Camera', 'droid.center', enabled=up and awake and not estop)
        add('Open Droid View', 'open.droid')
        perm = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Permissions', None, '')
        sub = AppKit.NSMenu.alloc().init(); sub.setAutoenablesItems_(False)
        for k, v in st['permissions'].items():
            sub.addItem_(self._item(f'{k.title()}: {v}', ('settings.open', k)))
        perm.setSubmenu_(sub); menu.addItem_(perm)
        add('Refresh Droid Peripherals', 'droid.refresh', enabled=up)
        sep()
        add('Mac', None)
        add('Lock Mac', 'mac.lock'); add('Turn Display Off', 'mac.display_off')
        add('Mac Status…', lambda: self._mac_status())
        sep()
        add('Reload', lambda: self.actions.window and self.actions.window.evaluate_js('location.reload()'))
        add('Open in Browser', 'open.browser')
        add('Quit Jaeger (NexusUI)', lambda: self.quit_app())

    @objc.python_method
    def _item(self, title, what, enabled=True, checked=False):
        it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, 'picked:' if what else None, '')
        it.setTarget_(self); it.setEnabled_(bool(what) and enabled)
        if checked: it.setState_(AppKit.NSControlStateValueOn)
        it.setTag_(len(self.handlers)); self.handlers[len(self.handlers)] = what
        return it

    @objc.python_method
    def _add(self, title, what, enabled=True, checked=False):
        self.menu.addItem_(self._item(title, what, enabled, checked))

    def picked_(self, sender):
        what = self.handlers.get(sender.tag())
        if isinstance(what, tuple) and what[0].startswith('stack.'):
            if alert(what[1], 'The Gateway and Main screen go with it.', (what[0].split('.')[1].title(), 'Cancel')) != 0:
                return
            what = what[0]
        self.run(what)

    @objc.python_method
    def run(self, what):
        def go():
            try:
                if callable(what): what()
                elif isinstance(what, tuple): self.actions.run(*what)
                else: self.actions.run(what)
            except Exception as e:  # noqa: BLE001 — a menu click must never kill the app
                AppHelper.callAfter(alert, 'Jaeger', str(e))
            AppHelper.callAfter(self.refresh)
        threading.Thread(target=go, daemon=True).start()

    @objc.python_method
    def _mac_status(self):
        s = shell.mac_status()
        AppHelper.callAfter(alert, 'Mac Status', f"Uptime: {s['uptime']}\nDisk free: {s['disk_free']}\nBattery: {s['battery']}")


class Hotkey:
    """Global hotkey (Swift: Hotkey.swift). ponytail: NSEvent monitors, so other apps' keys need Accessibility
    permission; a Carbon RegisterEventHotKey shim would need none."""

    def __init__(self, on_press):
        self.on_press, self.monitors, self.spec = on_press, [], None

    def set(self, spec: str | None):
        for m in self.monitors:
            AppKit.NSEvent.removeMonitor_(m)
        self.monitors, self.spec = [], spec
        if not spec:
            return
        code, mask = parse_hotkey(spec)
        hit = lambda e: e.keyCode() == code and (e.modifierFlags() & DEVICE_MODS) == mask
        def glob(e):
            if hit(e): self.on_press()
        def local(e):
            if hit(e): self.on_press(); return None
            return e
        self.monitors = [AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, glob),
                         AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, local)]


def install(actions: shell.Actions, quit_app, pill):
    """Menu-bar item + hotkey; call on the main thread. Returns (menu, hotkey)."""
    menu = Menu.alloc().initWithActions_quit_pill_(actions, quit_app, pill)
    hot = Hotkey(lambda: menu.run('window.toggle'))
    s = shell.load()
    hot.set(None if s['paused'] else s['hotkey'])
    actions.on_pause = lambda paused: AppHelper.callAfter(hot.set, None if paused else shell.load()['hotkey'])
    actions.mon.on_change = lambda: AppHelper.callAfter(menu.refresh)
    return menu, hot


if __name__ == '__main__':
    assert parse_hotkey('ctrl-opt-space') == (49, MODS['ctrl'] | MODS['opt'])
    assert parse_hotkey('opt-space') == (49, MODS['opt'])
    assert parse_hotkey('ctrl-opt-j') == (38, MODS['ctrl'] | MODS['opt'])
    print('native self-check ok')
