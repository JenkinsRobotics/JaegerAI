#!/usr/bin/env node
// Headless agent context-menu shots (mock, ?agentspec=1 = gateway on the agent-menu spec): phone 390×844 dark
// (menu, then More) and Mac 1086×782 right-click. Never opens a visible window.
// Usage: node scripts/agent-menu-shots.mjs http://127.0.0.1:<port>/ <outdir>
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";
const [base, out = "screenshots/agent-menu"] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(base ?? "")) throw new Error("pass a http://127.0.0.1:<port>/ URL");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { errors: [] };
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
await ctx.addInitScript(() => localStorage.setItem("aether-appearance", "dark"));
const p = await ctx.newPage(); p.on("pageerror", (e) => report.errors.push(String(e)));
await p.goto(base + "?mock=1&agentspec=1", { waitUntil: "networkidle" }); await p.waitForSelector(".jg-prow");
await p.locator('.jg-prow[data-agent-id="agent:gateway-webui"]').click({ button: "right" }); await p.waitForSelector(".jg-amenu"); await p.waitForTimeout(300);
await p.screenshot({ path: `${out}/ours-phone-menu.png` });
const items = (sel) => p.$$eval(`${sel} [role=menuitem]`, (b) => b.map((x) => x.textContent.replace(/[\uE000-\uF8FF]/g, "").trim()));
report.phoneMenu = await items(".jg-amenu__card:not(.jg-amenu__more)");
await p.locator(".jg-amenu__item", { hasText: "More" }).first().click(); await p.waitForSelector(".jg-amenu__more"); await p.waitForTimeout(300);
await p.screenshot({ path: `${out}/ours-phone-more.png` });
report.phoneMore = await items(".jg-amenu__more");
await p.locator(".jg-amenu__more .jg-amenu__item", { hasText: "Delete" }).click(); await p.waitForSelector(".jg-aprompt");
await p.screenshot({ path: `${out}/ours-phone-delete-confirm.png` });
await p.locator(".jg-aprompt button", { hasText: "Cancel" }).click(); await p.waitForTimeout(200);
report.afterCancelRows = await p.$$eval(".jg-prow", (r) => r.map((x) => x.dataset.agentId).includes("agent:gateway-webui"));
const live = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
const q = await live.newPage(); await q.goto(base + "?mock=1", { waitUntil: "networkidle" }); await q.waitForSelector(".jg-prow");
await q.locator('.jg-prow[data-agent-id="agent:gateway-webui"]').click({ button: "right" }); await q.waitForSelector(".jg-amenu");
report.todayGatewayMenu = await q.$$eval(".jg-amenu [role=menuitem]", (b) => b.map((x) => x.textContent.replace(/[\uE000-\uF8FF]/g, "").trim()));
const d = await browser.newPage({ viewport: { width: 1086, height: 782 } });
await d.goto(base + "?mock=1&agentspec=1&host=macos", { waitUntil: "networkidle" }); await d.waitForSelector('.jg-agent-list [data-agent-id]');
await d.locator('.jg-agent-list [data-agent-id="agent:gateway-webui"]').click({ button: "right" }); await d.waitForSelector(".jg-amenu"); await d.waitForTimeout(300);
await d.screenshot({ path: `${out}/ours-mac-menu.png` });
report.mac = { phone: await d.evaluate(() => document.documentElement.classList.contains("jg-phone")), items: await d.$$eval(".jg-amenu [role=menuitem]", (b) => b.length) };
console.log(JSON.stringify(report));
await browser.close();
