"""Jaeger AI in its own NexusUI window: `python -m jaeger_ai.interfaces.nexus` (`--browser` serves the same screen).

Beside the Swift Mac app and the WebUI (:8790), not instead of them. It talks to the running Gateway (:33418);
start that first (`./jaeger start`, or Start Jaeger stack… in the menu). The screen is built from web/ into
~/.cache/jaeger/nexus-ui/dist (outside the repo) on first run or with --build.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import serve, shell
from .gateway import Bridge, Gateway

WEB = Path(__file__).with_name('web')
LOOK = Path(__file__).with_name('look.json')   # Jaeger's own frozen screen look: the character owns it, the app never makes one
KEEP = []   # the menu-bar item and hotkey live as long as the app
SUGGEST = ['What can you do?', 'What is on my schedule today?', 'Summarize my unread mail', 'What time is it?']


def build():
    """npm ci + vite build into the screen folder outside the repo (node_modules stay git-ignored in web/)."""
    npm = shutil.which('npm') or sys.exit('Building the screen needs Node (npm).')
    if not (WEB / 'node_modules').is_dir():
        subprocess.run([npm, 'ci', '--no-audit', '--no-fund'], cwd=WEB, check=True)
    subprocess.run([npm, 'run', 'build', '--', '--outDir', str(serve.SCREEN), '--emptyOutDir'], cwd=WEB, check=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--browser', action='store_true', help='serve the screen for a browser instead of opening a window')
    p.add_argument('--port', type=int, default=None, help='screen port (default 8795 with --browser, any free port otherwise)')
    p.add_argument('--gateway', help='Gateway URL (default http://127.0.0.1:33418)')
    p.add_argument('--open', metavar='LINK', help='open a jaeger:// deep link (jaeger://conversation/<id>, jaeger://notifications)')
    p.add_argument('--build', action='store_true', help='rebuild the screen first')
    p.add_argument('--no-voice', action='store_true', help='no avatar voice (JAEGER_VOICE_PYTHON is used otherwise)')
    a = p.parse_args(argv)
    if a.build or not (serve.SCREEN / 'index.html').is_file():
        build()

    gw = Gateway(a.gateway)
    bridge = Bridge(gw)
    if not a.no_voice:
        from .voice import Voice
        bridge.voice = Voice(log=shell.STATE / 'nexus-voice.log').start()
    bridge.start()
    mon = shell.Monitors(gw)
    actions = shell.Actions(gw, mon, bridge)
    port = a.port if a.port is not None else (8795 if a.browser else 0)
    screen = serve.Screen(bridge, actions, {'name': 'Jaeger', 'title': 'Jaeger AI', 'suggestions': SUGGEST,
                                            'gateway': gw.url, 'webui': shell.WEBUI, 'face': json.loads(LOOK.read_text())}, port).start()
    mon.start()
    if a.open:
        screen.open_link(a.open)
    print(f'Jaeger AI (NexusUI): {screen.url}  ·  Gateway {gw.url}', flush=True)
    try:
        if a.browser:
            while True: time.sleep(1)
        else:
            run_window(screen, actions)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close(); screen.stop()
        if bridge.voice: bridge.voice.close()


def run_window(screen, actions):
    import webview
    from .window import grant_media
    grant_media()
    quitting = {'now': False}
    main = webview.create_window('Jaeger AI', screen.url, width=1280, height=820, min_size=(900, 600),
                                 background_color='#111722')
    pill = webview.create_window('Ask Jaeger', screen.url + '#pill', width=520, height=240, frameless=True,
                                 easy_drag=True, on_top=True, hidden=True, background_color='#171f2b')
    actions.window = main

    def hide_instead(win):   # the close button hides (Swift: windowShouldClose); Quit is in the menu
        def closing():
            if quitting['now']: return True
            win.hide()
            if win is main: actions.shown = False
            return False
        return closing
    main.events.closing += hide_instead(main)
    pill.events.closing += hide_instead(pill)

    def quit_app():
        quitting['now'] = True
        for w in list(webview.windows): w.destroy()

    def started():
        from PyObjCTools import AppHelper
        from . import native
        def toggle_pill():
            pill.show()
        def install():
            try:
                KEEP.append(native.install(actions, quit_app, toggle_pill))
                print('Menu-bar item and hotkey are on.', flush=True)
            except Exception:  # noqa: BLE001 — the window still works without them; say why they are missing
                import traceback; traceback.print_exc()
        AppHelper.callAfter(install)
    webview.start(started)


if __name__ == '__main__':
    main()
