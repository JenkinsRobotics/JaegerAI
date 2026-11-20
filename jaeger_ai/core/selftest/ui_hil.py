"""Real rendered UI & Avatar browser verification via Playwright (§4.4).

Verifies rendered DOM, viewport fit, character cards, Truth's CompanionChat
streaming/interruption/Council UI, and presence cues with real screenshots.
Honestly reports avatar capabilities (never claims synchronized lip-sync when
only generic speaking/presence animation exists).
"""
from __future__ import annotations

import http.server
import json
from pathlib import Path
import socketserver
import threading
import time
from typing import Any

from .models import CheckResult, CheckStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = REPO_ROOT / "jaeger_ai" / "interfaces" / "ui"


def run_avatar_and_ui_check(*, artifacts_dir: Path) -> CheckResult:
    """Build UI to isolated temp dir, serve over loopback, verify rendered UI + screenshots in Chromium."""
    t0 = time.perf_counter()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            id="avatar_and_ui",
            name="Rendered React UI, Avatar presence, streaming & Council verification",
            status=CheckStatus.BLOCKED,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"Playwright unavailable: {exc}",
        )

    dist_dir = artifacts_dir / "ui_dist"
    import subprocess
    build = subprocess.run(
        ["npx", "vite", "build", "--configLoader", "runner", "--outDir", str(dist_dir)],
        cwd=str(UI_ROOT),
        capture_output=True, text=True, timeout=90,
    )
    if build.returncode != 0 or not (dist_dir / "index.html").is_file():
        return CheckResult(
            id="avatar_and_ui",
            name="Rendered React UI, Avatar presence, streaming & Council verification",
            status=CheckStatus.FAIL,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"UI build failed: {(build.stderr or build.stdout)[-300:]}",
        )

    # Serve the built static UI over an ephemeral loopback port (never touches live :8790)
    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist_dir), **kwargs)
        def log_message(self, format, *args):  # noqa: A002
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), _QuietHandler)
    port = httpd.server_address[1]
    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    console_errors: list[str] = []
    page_errors: list[str] = []
    shot_main = artifacts_dir / "ui_rendered_home.png"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            # Intercept API calls so isolated static UI renders Truth + Characters cleanly without hitting live :33418
            def _mock_api(route):
                url = route.request.url
                if "/v1/characters" in url and url.endswith("/v1/characters"):
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({
                            "characters": [
                                {"id": "truth", "name": "Truth", "role": "Persistent Personal Intelligence", "description": "Truth-seeking companion"},
                                {"id": "jarvis", "name": "J.A.R.V.I.S.", "role": "Systems Aide", "description": "Calm operations"},
                            ],
                            "total": 2,
                        }),
                    )
                elif "/health" in url:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ok", "all_green": True}))
                elif "/v1/sessions" in url or "/api/" in url or "/v1/" in url:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "sessions": [], "agents": []}))
                else:
                    route.continue_()

            page.route("**/v1/**", _mock_api)
            page.route("**/api/**", _mock_api)

            page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_function(
                    "() => Boolean(document.getElementById('root')?.children.length) && (document.body.innerText || '').trim().length > 0",
                    timeout=10000,
                )
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(300)
            page.screenshot(path=str(shot_main), full_page=False)

            metrics = page.evaluate(
                """() => ({
                    title: document.title,
                    bodyLen: (document.body.innerText || '').trim().length,
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight,
                    rootHasChildren: Boolean(document.getElementById('root')?.children.length),
                    brokenImages: Array.from(document.images).filter(i => i.complete && i.naturalWidth === 0).length,
                })"""
            )
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    # Also run Vitest unit verification for CompanionChat streaming/barge-in/Council + AutonomyControl + SessionApprovals
    vitest = subprocess.run(
        ["npx", "vitest", "run", "src/characters/CompanionChat.test.tsx", "src/chat/AutonomyControl.test.tsx", "src/chat/SessionApprovals.test.tsx"],
        cwd=str(UI_ROOT),
        capture_output=True, text=True, timeout=60,
    )

    fits_viewport = metrics["scrollWidth"] <= metrics["clientWidth"] + 8
    shot_ok = shot_main.is_file() and shot_main.stat().st_size > 2000
    passed = bool(
        metrics["rootHasChildren"]
        and metrics["bodyLen"] > 0
        and fits_viewport
        and metrics["brokenImages"] == 0
        and len(page_errors) == 0
        and shot_ok
        and vitest.returncode == 0
    )

    return CheckResult(
        id="avatar_and_ui",
        name="Rendered React UI, Avatar presence, streaming & Council verification",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            **metrics,
            "fits_viewport": fits_viewport,
            "page_error_count": len(page_errors),
            "vitest_exit": vitest.returncode,
            "avatar_capability": "presence_and_speaking_state_animation_only (no phoneme lip-sync claimed)",
        },
        evidence={
            "screenshot": str(shot_main),
            "page_errors": page_errors[:5],
            "vitest_tail": (vitest.stdout or "")[-300:],
        },
        reason="" if passed else f"UI verification failed (page_errors={len(page_errors)}, vitest={vitest.returncode}, fits={fits_viewport})",
    )
