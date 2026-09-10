#!/usr/bin/env python3
"""Opt-in real browser ↔ production Swift view-model handoff. Uses model tokens.

Requires the deployed WebUI, native bridge and playwright's Chromium. Never
captures screens or grants tool permissions. Verification exchanges are retained.
"""
import argparse
import os
from pathlib import Path
import subprocess
import uuid

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    word = 'HANDOFF-' + uuid.uuid4().hex[:10]
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until='domcontentloaded')
        if page.locator('#profileChip').inner_text().strip() != 'Jaeger':
            page.locator('#profileChip').click()
            page.get_by_text('Jaeger', exact=True).click()
        page.wait_for_url('**/session/*', timeout=20000)
        status = page.locator('#jaeger-conversation-status')
        status.wait_for(state='visible', timeout=20000)
        page.wait_for_function('() => document.querySelector("#jaeger-conversation-status")?.innerText.startsWith("Dispatcher")', timeout=20000)
        session_url = page.url
        page.locator('#msg').fill(f'Cross-interface verification only. The newest identifier for this conversation is {word}. Reply exactly {word}. No tools or long-term memory writes.')
        page.locator('#btnSend').click()
        # Match assistant output, not merely the submitted user prompt.
        page.wait_for_function('(word) => [...document.querySelectorAll("#messages .assistant-turn")].some(e => e.innerText.includes(word))', arg=word, timeout=120000)
        print('PASS: browser composer produced a real assistant answer', word, flush=True)
        result = subprocess.run(['swift', 'test', '--package-path', str(ROOT / 'jaeger_ai/interfaces/swift'),
                                 '--filter', 'DispatcherLiveTests/testLiveDesktopContinuation'],
                                cwd=ROOT, env={**os.environ, 'JAEGER_CONTINUITY_WORD': word},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        print(result.stdout, flush=True)
        if result.returncode:
            raise RuntimeError('Production Mac client verification failed')
        page.wait_for_function('(word) => [...document.querySelectorAll("#messages .assistant-turn")].some(e => e.innerText.includes(word) && e.innerText.includes("MAC-CONFIRMED"))', arg=word, timeout=20000)
        assert page.url == session_url
        print('PASS: browser rendered the Mac reply without changing conversations', flush=True)
        # A dropped browser connection must only re-observe saved history.
        page.context.set_offline(True)
        page.wait_for_timeout(2500)
        page.context.set_offline(False)
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function('(word) => [...document.querySelectorAll("#messages .assistant-turn")].some(e => e.innerText.includes(word) && e.innerText.includes("MAC-CONFIRMED"))', arg=word, timeout=20000)
        page.locator('#msg').fill('Final browser continuation check: repeat the newest HANDOFF identifier followed by WEB-CONFIRMED. No tools.')
        page.locator('#btnSend').click()
        page.wait_for_function('(word) => [...document.querySelectorAll("#messages .assistant-turn")].some(e => e.innerText.includes(word) && e.innerText.includes("WEB-CONFIRMED"))', arg=word, timeout=120000)
        assert not errors, errors
        print('PASS: WebUI → Mac → WebUI continuity and offline/reload recovery', word, session_url, flush=True)
        browser.close()


if __name__ == '__main__':
    main()
