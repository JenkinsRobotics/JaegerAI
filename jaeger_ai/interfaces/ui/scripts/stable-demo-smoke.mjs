// Read-only live smoke. Does not send chat, create tasks, approve actions or restart services.
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
const base = "http://127.0.0.1:8790";
const session = process.env.JAEGER_DEMO_SESSION;
const taskId = process.env.JAEGER_DEMO_TASK;
await mkdir("test-results", { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  if (session) await page.addInitScript(s => localStorage.setItem("jaeger.stable-demo.session.v1", s), session);
  await page.goto(base, { waitUntil: "domcontentloaded" });
  await page.locator("[data-stable-demo]").waitFor();
  await page.getByRole("button", { name: "Chat", exact: true }).waitFor();
  if (session) await page.locator(".jg-bubble--assistant").first().waitFor();
  else await page.getByRole("button", { name: "Start conversation" }).waitFor();
  await page.screenshot({ path: "test-results/stable-demo-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByRole("heading", { name: "Tasks", exact: true }).waitFor();
  if (taskId) {
    const data = await (await page.request.get(`${base}/v1/tasks`)).json();
    const task = (Array.isArray(data) ? data : data.tasks).find(t => t.task_id === taskId);
    assert.equal(task?.state, "completed_verified");
    assert.ok(task.payload?.verification?.some(receipt => receipt.kind === "file_sha256" && receipt.sha256));
    await page.getByRole("searchbox", { name: "Search tasks" }).fill(task.goal);
    await page.getByText(task.goal, { exact: true }).first().waitFor();
    await page.screenshot({ path: "test-results/stable-demo-verified-task.png", fullPage: true });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Tasks", exact: true }).click();
    await page.getByRole("searchbox", { name: "Search tasks" }).fill(task.goal);
    await page.getByText(task.goal, { exact: true }).first().waitFor();
    console.log("Verified task and evidence survive UI reload:", taskId);
  }
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  if (session) await page.locator(".jg-bubble--assistant").first().waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "domcontentloaded" });
  if (session) await page.locator(".jg-bubble--assistant").first().waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: "test-results/stable-demo-phone.png", fullPage: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.screenshot({ path: "test-results/stable-demo-phone-dark.png", fullPage: true });
  assert.deepEqual(errors, []);
  await writeFile("test-results/stable-demo-smoke.json", JSON.stringify({ live: base, session, taskId, errors, passed: true }, null, 2));
  console.log("PASS: live Chat/Tasks, history reload, desktop/phone, no horizontal overflow or browser exceptions");
} finally { await browser.close(); }
