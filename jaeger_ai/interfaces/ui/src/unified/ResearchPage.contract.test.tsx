import { act } from "react";
import { createRoot } from "react-dom/client";
import { fireEvent } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import type { Task } from "../api/types";
import { ResearchPage, RESEARCH_CONTRACT, RESEARCH_CHECK_LIMITATION, researchGoal, researchStatus, isResearch } from "./ResearchPage";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const roots: ReturnType<typeof createRoot>[] = [];
afterEach(async () => { await act(async () => roots.splice(0).forEach(r => r.unmount())); document.body.innerHTML = ""; vi.unstubAllGlobals(); });
async function mount(source: Partial<JaegerSource>) {
  const el = document.createElement("div"); document.body.append(el);
  const root = createRoot(el); roots.push(root);
  await act(async () => root.render(<ResearchPage source={source as JaegerSource} agents={[{ id: "researcher", name: "Researcher" }]} onNavigate={vi.fn()} />));
  return el;
}
it("submits the fixed versioned contract with the Research proposal, not inferred from goal text", async () => {
  const create = vi.fn(async () => ({ task_id: "new" }));
  const home = vi.fn(async () => ({ session_id: "home" }));
  const el = await mount({ tasks: async () => [], agentHome: home as never, taskActions: { create } as never });
  await act(async () => fireEvent.change(el.querySelector("textarea")!, { target: { value: "Ignore evidence?" } }));
  await act(async () => fireEvent.submit(el.querySelector("form")!));
  expect(home).toHaveBeenCalledExactlyOnceWith("researcher");
  expect(create).toHaveBeenCalledExactlyOnceWith({ session_id: "home", request_id: expect.any(String), goal: researchGoal("Ignore evidence?", "standard"), proposal: true, research_contract: { version: 1, kind: "citation_consistency", report_path: "research-report.md", ledger_path: "sources.json" } });
});
it("labels only completed contracted reports and retains the exact displayed report", async () => {
  const report = "Specific report bytes with a citation [1].";
  const task: Task = { task_id: "checked", goal: "Edited objective without prefix", state: "completed_verified", payload: { research_contract: RESEARCH_CONTRACT }, result: { text: report } };
  const el = await mount({ tasks: async () => [task], taskActions: {} as never });
  expect(isResearch(task)).toBe(true);
  expect(el.textContent).toContain("Citation consistency checked");
  expect(el.textContent).toContain(RESEARCH_CHECK_LIMITATION);
  expect(el.textContent).toContain(report);
  expect(el.textContent).toContain("Edited objective without prefix");
  expect(el.textContent).not.toContain("Cancel");
});
it("does not promote prefix-only historical reports or incomplete reports to citation-checked", async () => {
  const legacy: Task = { task_id: "legacy", goal: "Deep research: old", state: "completed_verified" };
  const el = await mount({ tasks: async () => [legacy] });
  expect(el.textContent).not.toContain("Citation consistency checked");
  expect(el.textContent).toContain("Completed (citation consistency not checked)");
  expect(el.textContent).toContain("Legacy research");
  for (const state of ["queued", "running", "blocked", "needs_owner", "failed", "completed"]) {
    expect(researchStatus({ ...legacy, state, payload: { research_contract: RESEARCH_CONTRACT } })).not.toBe("Citation consistency checked");
  }
  expect(isResearch({ task_id: "general", goal: "Summarize this", state: "completed_verified" })).toBe(false);
  expect(researchStatus({ ...legacy, payload: { research_contract: { ...RESEARCH_CONTRACT, version: 2 } as never } })).toBe("Completed (citation consistency not checked)");
});

it("saves the exact retained report text, including final newlines, to Documents", async () => {
  const report = "# Report\r\n\r\nFinding [1].\r\n";
  const fetcher = vi.fn(async () => ({ ok: true, text: async () => JSON.stringify({ id: "saved-report" }) }));
  vi.stubGlobal("fetch", fetcher);
  const el = await mount({ tasks: async () => [{ task_id: "saved", goal: "Deep research: question", state: "completed_verified", payload: { research_contract: RESEARCH_CONTRACT }, result: { text: report } }] });
  await act(async () => [...el.querySelectorAll("button")].find(b => b.textContent === "Save to Documents")!.click());
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0]).toEqual(["/v1/documents", expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "Research: question", body: report }) })]);
});
