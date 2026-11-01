import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { BacklogPage } from "./BacklogPage";
import { ToastProvider } from "./ui";
import { matchBacklog, type BacklogTask } from "./backlog";

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

const task = (over: Partial<BacklogTask>): BacklogTask => ({ id: "bl-0000000001", title: "T", detail: "", source: "md", status: "open", priority: "P1", worker: "", handoff_id: null, handoff_thread: null, last_note: "", created_at: 1, updated_at: Date.now() / 1000, ...over });
const TASKS = [
  task({ id: "bl-0000000001", title: "Sign the Mac app", status: "needs_ok", priority: "P0" }),
  task({ id: "bl-0000000002", title: "Fix failing tests", status: "in_progress", worker: "ares", last_note: "assigned to ares" }),
  task({ id: "bl-0000000003", title: "Ollama loopback", status: "done", worker: "rackpc" }),
];

async function mount(params = "") {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url: String(url), method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (String(url).startsWith("/v1/activity")) return Response.json({ items: [], has_more: false });
    if (method === "GET") return Response.json({ tasks: TASKS, counts: { needs_ok: 1, in_progress: 1, done: 1 }, now: 0 });
    if (String(url).endsWith("/assign")) return Response.json({ task: { ...TASKS[0], worker: "muse", status: "in_progress" }, handoff: { id: "h", thread: "t", to: "muse" } });
    return Response.json({ task: { ...TASKS[0], status: "open" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<ToastProvider><BacklogPage params={new URLSearchParams(params)} /></ToastProvider>); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  return { el, calls };
}

it("filters: not-done by default, deep-linked status and worker", () => {
  const notDone = TASKS.filter(matchBacklog({ status: "active", priority: "", worker: "", q: "" }));
  expect(notDone.map((t) => t.id)).toEqual(["bl-0000000001", "bl-0000000002"]);
  expect(TASKS.filter(matchBacklog({ status: "", priority: "P0", worker: "", q: "" }))).toHaveLength(1);
  expect(TASKS.filter(matchBacklog({ status: "", priority: "", worker: "rackpc", q: "" }))[0].title).toBe("Ollama loopback");
  expect(TASKS.filter(matchBacklog({ status: "", priority: "", worker: "none", q: "sign" }))).toHaveLength(1);
});

it("lists tasks, approves a needs_ok task and assigns a worker", async () => {
  const { el, calls } = await mount();
  expect(el.textContent).toContain("Sign the Mac app");
  expect(el.textContent).toContain("Fix failing tests");
  expect(el.textContent).not.toContain("Ollama loopback"); // done hidden by default
  const approve = [...el.querySelectorAll("button")].find((b) => b.textContent === "Approve")!;
  await act(async () => { approve.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(calls.find((c) => c.method === "POST" && c.url === "/v1/backlog/bl-0000000001")?.body).toEqual({ status: "open" });
  const assign = el.querySelector<HTMLSelectElement>('select[aria-label="Assign Sign the Mac app"]')!;
  await act(async () => { assign.value = "muse"; assign.dispatchEvent(new Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 0)); });
  expect(calls.find((c) => c.url.endsWith("/assign"))?.body).toEqual({ worker: "muse" });
});

it("inline priority edit posts the change", async () => {
  const { el, calls } = await mount("status=in_progress");
  expect(el.textContent).not.toContain("Sign the Mac app");
  const prio = el.querySelector<HTMLSelectElement>('select[aria-label="Priority of Fix failing tests"]')!;
  await act(async () => { prio.value = "P0"; prio.dispatchEvent(new Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 0)); });
  expect(calls.find((c) => c.url === "/v1/backlog/bl-0000000002" && c.method === "POST")?.body).toEqual({ priority: "P0" });
});
