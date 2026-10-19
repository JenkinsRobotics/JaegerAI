#!/usr/bin/env node
// Headless batch of desktop popups at Grok's capture size (1018×736 @2x, light, host=macos), one popup open per
// page: ⌘K, Settings, message menu, approval card, question card. Never opens a visible window.
// Usage: node scripts/popup-shots.mjs http://127.0.0.1:<port>/ <outdir>
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";
const [base, out = "screenshots/popups"] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(base ?? "")) throw new Error("pass a http://127.0.0.1:<port>/ URL");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {};
async function shot(name, act, check) {
  const p = await browser.newPage({ viewport: { width: 1018, height: 736 }, deviceScaleFactor: 2 });
  const errors = []; p.on("pageerror", (e) => errors.push(String(e)));
  await p.goto(base + "?mock=1&host=macos", { waitUntil: "networkidle" }); await p.waitForSelector(".jg-bubble--assistant"); await p.waitForTimeout(300);
  await act(p); await p.waitForTimeout(400);
  await p.screenshot({ path: `${out}/ours-${name}.png` });
  report[name] = { ...(await p.evaluate(check)), errors: errors.length };
  await p.close();
}
await shot("cmdk", (p) => p.keyboard.press("Meta+k"), () => ({ open: [...document.querySelectorAll('[role="menu"],[role="dialog"]')].map((m) => m.getAttribute("aria-label")), rows: document.querySelectorAll(".jg-palette__row").length }));
await shot("settings", (p) => p.keyboard.press("Meta+,"), () => ({ open: [...document.querySelectorAll('[role="menu"],[role="dialog"]')].map((m) => m.getAttribute("aria-label")), tabs: document.querySelectorAll(".jg-sheet__tab").length }));
await shot("message-menu", async (p) => { const b = p.locator(".jg-bubble--assistant").last(); const r = await b.boundingBox(); await p.mouse.click(r.x + r.width / 2, r.y + 20, { button: "right" }); },
  () => ({ open: [...document.querySelectorAll('[role="menu"],[role="dialog"]')].map((m) => m.getAttribute("aria-label")), items: document.querySelectorAll('[aria-label="Message actions"] [role="menuitem"]').length }));
await shot("question-card", async (p) => { await p.locator(".jg-question").first().scrollIntoViewIfNeeded(); await p.evaluate(() => document.querySelector(".jg-question").scrollIntoView({ block: "center" })); },
  () => ({ open: [...document.querySelectorAll('[role="menu"],[role="dialog"]')].map((m) => m.getAttribute("aria-label")), question: !!document.querySelector(".jg-question"), chosen: document.querySelector(".jg-question__option.is-chosen")?.textContent }));
await shot("approval-card", async (p) => { await p.locator('.jg-agent-list [data-agent-id="agent:agents-view"] button').first().click(); await p.waitForSelector(".jg-approval"); await p.evaluate(() => document.querySelector(".jg-approval").scrollIntoView({ block: "center" })); },
  () => ({ open: [...document.querySelectorAll('[role="menu"],[role="dialog"]')].map((m) => m.getAttribute("aria-label")), heading: document.querySelector(".jg-approval__title")?.textContent, buttons: [...document.querySelectorAll(".jg-approval__actions button")].map((b) => b.textContent) }));
console.log(JSON.stringify(report));
await browser.close();
