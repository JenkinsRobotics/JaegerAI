#!/usr/bin/env node
// Headless screenshots of the mock screen. Never opens a visible window.
// Usage: node scripts/screenshots.mjs http://127.0.0.1:<port>/
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const base = process.argv[2];
if (!base || !/^http:\/\/127\.0\.0\.1:\d+\//.test(base)) throw new Error("pass a http://127.0.0.1:<port>/ URL");
mkdirSync("screenshots", { recursive: true });
const browser = await chromium.launch({ headless: true });
const shots = [
  ["jaeger-ui-default.png", "?mock=1"],
  ["jaeger-ui-macos.png", "?mock=1&host=macos"],
  ["jaeger-ui-tasks.png", "?mock=1", "Tasks"],
];
for (const [file, query, click] of shots) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(base + query, { waitUntil: "networkidle" });
  await page.waitForSelector(".jg-bubble--assistant");
  if (click) { await page.locator(".jg-nav-entry", { hasText: click }).click(); await page.waitForSelector(".jg-card"); }
  await page.waitForTimeout(300);
  await page.screenshot({ path: `screenshots/${file}` });
  console.log(`screenshots/${file}`, errors.length ? `errors: ${errors.join(" | ")}` : "no console errors");
  await page.close();
}
await browser.close();
