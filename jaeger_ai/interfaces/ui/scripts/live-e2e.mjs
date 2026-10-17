#!/usr/bin/env node
// Headless end-to-end check against a running Jaeger stack (no mock).
// Start `JAEGER_WEBUI_URL=http://127.0.0.1:<webui> npm run dev -- --port <p>`, then
//   node scripts/live-e2e.mjs http://127.0.0.1:<p>/
// It never prints request headers, so no credential can show up in its output.
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const base = process.argv[2];
if (!base || !/^http:\/\/127\.0\.0\.1:\d+\//.test(base)) throw new Error("pass a http://127.0.0.1:<port>/ URL");
mkdirSync("screenshots", { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
const page = await context.newPage();
const calls = [];
page.on("response", (r) => { const u = new URL(r.url()); if (/^\/(v1|api)\//.test(u.pathname)) calls.push(`${r.request().method()} ${u.pathname}${u.search} -> ${r.status()}`); });
page.on("requestfailed", (r) => { const u = new URL(r.url()); if (/^\/(v1|api)\//.test(u.pathname)) calls.push(`${r.method()} ${u.pathname}${u.search} -> FAILED ${r.failure()?.errorText}`); });
page.on("pageerror", (e) => log("pageerror", String(e)));

const idle = () => page.waitForSelector('button.jg-send[aria-label="Send"]', { timeout: 180_000 });
const send = async (text) => {
  await page.fill(".jg-composer__input", text);
  await page.keyboard.press("Enter");
  await page.waitForSelector('button.jg-send[aria-label^="Stop"]', { timeout: 10_000 });
};
const lastAssistant = () => page.locator(".jg-turn").last().locator(".jg-bubble--assistant").allInnerTexts();

await page.goto(base, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".jg-supervisor", { timeout: 20_000 });
log("roster:", (await page.locator(".jg-supervisor__label, .jg-agent-row__name").allInnerTexts()).join(" | "));
log("tray:", await page.locator(".jg-tray").innerText());

await page.click(`button[aria-label="New chat"]`);
await page.waitForSelector(".jg-chat__empty", { timeout: 15_000 });
log("new chat created");

// Turn 1: plain streamed reply.
let t = Date.now();
await send("Reply with just the word: pong");
await idle();
log(`turn 1 done in ${((Date.now() - t) / 1000).toFixed(1)}s:`, JSON.stringify(await lastAssistant()).slice(0, 200));
await page.screenshot({ path: "screenshots/jaeger-ui-live.png" });

// Turn 2: same session (an old turn.finish exists), drop the network mid-stream to force a reconnect.
t = Date.now();
await send("Count from 1 to 5, one number per line.");
await page.waitForTimeout(4000);
await context.setOffline(true);
log("offline");
await page.waitForTimeout(1500);
await context.setOffline(false);
log("online");
await idle();
log(`turn 2 done in ${((Date.now() - t) / 1000).toFixed(1)}s:`, JSON.stringify(await lastAssistant()).slice(0, 200));

// Turn 3: cancel.
t = Date.now();
await send("Write a 300 word story about a lighthouse.");
await page.waitForTimeout(3000);
await page.getByRole("button", { name: /^Stop/ }).click();
await idle();
log(`turn 3 stopped after ${((Date.now() - t) / 1000).toFixed(1)}s:`, JSON.stringify(await lastAssistant()).slice(0, 160));

await page.click(".jg-nav-entry");
await page.waitForTimeout(1500);
log("tasks pane:", (await page.locator(".jg-tasks").innerText()).replace(/\s+/g, " ").slice(0, 160));
await page.screenshot({ path: "screenshots/jaeger-ui-live-tasks.png" });

console.log("\n--- API calls (method path -> status) ---");
const counts = new Map();
for (const c of calls) counts.set(c, (counts.get(c) ?? 0) + 1);
for (const [c, n] of counts) console.log(n > 1 ? `${c}  x${n}` : c);
await browser.close();
