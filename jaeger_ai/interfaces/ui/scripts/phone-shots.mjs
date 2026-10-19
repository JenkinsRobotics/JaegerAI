#!/usr/bin/env node
// Headless phone screenshots (390×844, touch, dark) of the mock build: list, chat, keyboard open (visual viewport
// reduced to 844-336). Plus a desktop check at 1086×782 (fine pointer) that the phone layout never applies.
// Never opens a visible window. Usage: node Scripts/phone-shots.mjs http://127.0.0.1:<port>/ <outdir>
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const [base, out = "screenshots/phone"] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(base ?? "")) throw new Error("pass a http://127.0.0.1:<port>/ URL");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {};
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
await phone.addInitScript(() => localStorage.setItem("aether-appearance", "dark"));
const p = await phone.newPage();
const errors = []; p.on("pageerror", (e) => errors.push(String(e)));
await p.goto(base + "?mock=1", { waitUntil: "networkidle" });
await p.waitForSelector(".jg-prow"); await p.waitForTimeout(400);
await p.screenshot({ path: `${out}/ours-list.png` });
report.list = await p.evaluate(() => ({ phone: document.documentElement.classList.contains("jg-phone"), shell: !!document.querySelector(".jg-shell"),
  rows: document.querySelectorAll(".jg-prow").length, minTap: Math.min(...[...document.querySelectorAll(".jg-phone-list button")].map((b) => Math.min(b.getBoundingClientRect().height, b.getBoundingClientRect().width))),
  unreadPill: document.querySelector(".jg-punread")?.textContent ?? null, overflowX: document.documentElement.scrollWidth > innerWidth }));
await p.tap(".jg-plead");
await p.waitForSelector(".jg-bubble--assistant"); await p.waitForTimeout(600);
await p.screenshot({ path: `${out}/ours-chat.png` });
report.chat = await p.evaluate(() => { const c = document.querySelector(".jg-composer").getBoundingClientRect(); return { bar: !!document.querySelector(".jg-pbar"),
  placeholder: document.querySelector(".jg-composer__input").placeholder, composerBottom: Math.round(c.bottom), pillHidden: getComputedStyle(document.querySelector(".jg-agent-pill-wrap") ?? document.body).display === "none",
  bubbleFont: getComputedStyle(document.querySelector(".jg-bubble--assistant")).fontSize, overflowX: document.documentElement.scrollWidth > innerWidth }; });
await p.setViewportSize({ width: 390, height: 508 }); // keyboard (336pt) takes the bottom of the visual viewport
await p.focus(".jg-composer__input"); await p.waitForTimeout(400);
await p.screenshot({ path: `${out}/ours-chat-keyboard.png` });
report.keyboard = await p.evaluate(() => ({ vvh: getComputedStyle(document.documentElement).getPropertyValue("--jg-vvh"), composerBottom: Math.round(document.querySelector(".jg-composer").getBoundingClientRect().bottom), vv: visualViewport.height }));
await p.setViewportSize({ width: 390, height: 844 });
await p.tap('[aria-label="Back"]'); await p.waitForSelector(".jg-prow");
report.back = true;
const d = await browser.newPage({ viewport: { width: 1086, height: 782 } });
await d.goto(base + "?mock=1&host=macos", { waitUntil: "networkidle" }); await d.waitForSelector(".jg-bubble--assistant"); await d.waitForTimeout(300);
await d.screenshot({ path: `${out}/ours-desktop-1086.png` });
report.desktop = await d.evaluate(() => ({ phone: document.documentElement.classList.contains("jg-phone"), shell: !!document.querySelector(".jg-shell"), phoneScreens: document.querySelectorAll(".jg-phone-screen").length }));
report.errors = errors;
console.log(JSON.stringify(report, null, 1));
await browser.close();
