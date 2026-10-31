import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import { PipelinePage, StageStepper, TaskBanner } from "./PipelinePage";
import { nextStage, stagePath } from "./pipeline";
import { ToastProvider } from "./ui";

const task = { task_id: "t-1", goal: "Write the launch brief", state: "running" };
const rec = { task_id: "t-1", stage: "research", revision: 2, history: [{ from: null, to: "intake", at: 1, note: null }, { from: "intake", to: "research", at: 2, note: null }], attachments: [{ id: "aaaaaaaaaaaa", kind: "source", ref: "https://example.com/a", label: "Spec", text: null, stage: "research", at: 3 }] };
const src = { tasks: async () => [task, { task_id: "t-2", goal: "Other", state: "succeeded" }] } as unknown as JaegerSource;

function stubFetch() {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url === "/v1/pipeline" && method === "GET") return json({ stages: [], items: { "t-1": rec } });
    if (url.startsWith("/v1/pipeline/t-1") && method === "PUT") return json({ ...rec, stage: "studio", revision: 3 });
    if (url === "/v1/studio/assets") return json({ assets: [{ id: "as1", name: "hero.png" }] });
    if (url.endsWith("/attachments") && method === "POST") return json({ id: "bbbbbbbbbbbb", kind: "asset", ref: "asset:as1", label: "hero.png", text: null, stage: "studio", at: 4 });
    return json({});
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("task pipeline", () => {
  it("orders stages and routes each to its tab with the task attached", () => {
    expect(nextStage(null)).toBe("intake");
    expect(nextStage("research")).toBe("studio");
    expect(nextStage("done")).toBeNull();
    expect(stagePath("research", "t 1")).toBe("/research?task=t%201");
    expect(stagePath("studio", "t")).toBe("/studio?task=t");
    expect(stagePath("production", "t")).toBe("/work/production?task=t");
    expect(stagePath("review", "t")).toBe("/work?task=t");
  });
  it("stepper marks done, current and upcoming stages", () => {
    const { container } = render(<StageStepper stage="studio" />);
    const states = [...container.querySelectorAll("li")].map((l) => l.getAttribute("data-state"));
    expect(states).toEqual(["done", "done", "current", "todo", "todo", "todo"]);
  });
  it("hub shows real stage + gateway state and advancing persists then opens the next tab", async () => {
    const calls = stubFetch();
    const go = vi.fn();
    render(<ToastProvider><PipelinePage source={src} params={new URLSearchParams()} onNavigate={go} /></ToastProvider>);
    await screen.findByText("Write the launch brief");
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("Start in Plan")).toBeTruthy(); // t-2 has no record: not faked into a stage
    fireEvent.click(screen.getByText("Advance to Studio"));
    await waitFor(() => expect(go).toHaveBeenCalledWith("/studio?task=t-1"));
    expect(calls.find((c) => c.method === "PUT")).toMatchObject({ url: "/v1/pipeline/t-1", body: { stage: "studio", expected_revision: 2 } });
  });
  it("Studio banner attaches an asset back to the task", async () => {
    const calls = stubFetch();
    render(<ToastProvider><TaskBanner source={src} taskId="t-1" stage="studio" onNavigate={vi.fn()} clearTo="/studio" /></ToastProvider>);
    await screen.findByText("Write the launch brief");
    fireEvent.click(screen.getByText("Attach asset"));
    fireEvent.click(await screen.findByText("hero.png"));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toMatchObject({ url: "/v1/pipeline/t-1/attachments", body: { kind: "asset", ref: "asset:as1", label: "hero.png" } }));
  });
});
