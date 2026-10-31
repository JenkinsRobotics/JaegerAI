// Headless shots + no-horizontal-scroll sweep for the orchestration harness.
// Usage: node scripts/orchestration-shots.mjs http://127.0.0.1:<port> <outdir>
import { chromium } from "playwright";
const [base = "http://127.0.0.1:5291", out = "/tmp/orch-shots"] = process.argv.slice(2);
const url = `${base}/orchestration-harness.html`;
const browser = await chromium.launch({ headless: true });
const shots = [
  ["expanded-inspector", 1440, 900, true],
  ["regular-overlay", 1024, 768, true],
  ["medium", 744, 1133, false],
  ["compact", 390, 844, false],
  ["compact-sheet", 390, 844, true],
];
const errors = [];
for (const [name, width, height, open] of shots) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  await page.goto(url);
  await page.getByText("Live", { exact: true }).waitFor();
  if (open) { await page.getByRole("button", { name: /Exchange/ }).first().click(); await page.getByLabel("Handoff details").waitFor(); }
  await page.screenshot({ path: `${out}/orchestration-${name}.png` });
  await page.close();
}
const page = await browser.newPage({ viewport: { width: 320, height: 800 } });
await page.goto(url); await page.getByText("Live", { exact: true }).waitFor();
const overflow = [];
for (let w = 320; w <= 2560; w += 40) {
  await page.setViewportSize({ width: w, height: 800 });
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  if (sw > w) overflow.push(`${w}:${sw}`);
}
const fail = await browser.newPage({ viewport: { width: 1024, height: 600 } });
await fail.goto(`${url}?fail=1`); await fail.getByText(/Gateway unreachable/).waitFor();
await fail.screenshot({ path: `${out}/orchestration-error.png` });
await browser.close();
console.log(JSON.stringify({ shots: shots.length + 1, overflow, errors }));
if (overflow.length || errors.length) process.exit(1);
